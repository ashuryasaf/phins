"""Tests for the security hardening modules: firewall, file scanner,
intrusion detector, and request sanitiser.

These tests run in isolation (no HTTP server) to pinpoint which security
primitive is broken.
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import List

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# FILE SCANNER
# ═══════════════════════════════════════════════════════════════════════════

class TestFileScanner:
    """Tests for security.file_scanner."""

    def test_clean_pdf_passes(self):
        from security.file_scanner import scan_file_bytes
        data = b"%PDF-1.4 some content here"
        v = scan_file_bytes(data, filename="report.pdf", declared_content_type="application/pdf")
        assert v.safe is True
        assert v.file_hash

    def test_clean_png_passes(self):
        from security.file_scanner import scan_file_bytes
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        v = scan_file_bytes(data, filename="photo.png", declared_content_type="image/png")
        assert v.safe is True

    def test_clean_jpeg_passes(self):
        from security.file_scanner import scan_file_bytes
        data = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        v = scan_file_bytes(data, filename="image.jpg", declared_content_type="image/jpeg")
        assert v.safe is True

    def test_exe_header_blocked(self):
        from security.file_scanner import scan_file_bytes
        data = b"MZ" + b"\x00" * 100
        v = scan_file_bytes(data, filename="payload.pdf")
        assert v.safe is False
        assert any("executable_header" in t for t in v.threats)

    def test_elf_header_blocked(self):
        from security.file_scanner import scan_file_bytes
        data = b"\x7fELF" + b"\x00" * 100
        v = scan_file_bytes(data, filename="binary.bin")
        assert v.safe is False

    def test_dangerous_extension_blocked(self):
        from security.file_scanner import scan_file_bytes
        data = b"some content"
        v = scan_file_bytes(data, filename="virus.exe")
        assert v.safe is False
        assert any("dangerous_extension" in t for t in v.threats)

    def test_double_extension_attack(self):
        from security.file_scanner import scan_file_bytes
        data = b"%PDF-1.4 content"
        v = scan_file_bytes(data, filename="report.exe.pdf")
        assert v.safe is False
        assert any("double_extension" in t for t in v.threats)

    def test_embedded_script_blocked(self):
        from security.file_scanner import scan_file_bytes
        data = b"%PDF-1.4 <script>alert('xss')</script>"
        v = scan_file_bytes(data, filename="malicious.pdf", declared_content_type="application/pdf")
        assert v.safe is False
        assert any("embedded_script" in t for t in v.threats)

    def test_content_type_mismatch(self):
        from security.file_scanner import scan_file_bytes
        data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        v = scan_file_bytes(data, filename="image.png", declared_content_type="application/pdf")
        assert v.safe is False
        assert any("content_type_mismatch" in t for t in v.threats)

    def test_oversized_file_blocked(self):
        from security.file_scanner import scan_file_bytes
        data = b"x" * 1000
        v = scan_file_bytes(data, filename="big.txt", max_size=500)
        assert v.safe is False
        assert any("file_too_large" in t for t in v.threats)

    def test_empty_file_blocked(self):
        from security.file_scanner import scan_file_bytes
        v = scan_file_bytes(b"", filename="empty.txt")
        assert v.safe is False
        assert any("empty_file" in t for t in v.threats)

    def test_macro_signature_detected(self):
        from security.file_scanner import scan_file_bytes
        data = b"\xd0\xcf\x11\xe0" + b"VBA project AutoOpen macro code"
        v = scan_file_bytes(data, filename="doc.doc")
        assert v.safe is False

    def test_shell_command_in_file(self):
        from security.file_scanner import scan_file_bytes
        data = b"#!/bin/bash\nrm -rf /\n" + b"\x00" * 50
        v = scan_file_bytes(data, filename="script.txt")
        assert v.safe is False
        assert any("macro_or_shell" in t for t in v.threats)

    def test_base64_scanning_valid(self):
        from security.file_scanner import scan_base64_payload
        raw = b"%PDF-1.4 clean content"
        b64 = base64.b64encode(raw).decode()
        v = scan_base64_payload(b64, filename="report.pdf", declared_content_type="application/pdf")
        assert v.safe is True

    def test_base64_scanning_malicious(self):
        from security.file_scanner import scan_base64_payload
        raw = b"MZ" + b"\x00" * 200  # EXE header
        b64 = base64.b64encode(raw).decode()
        v = scan_base64_payload(b64, filename="payload.pdf")
        assert v.safe is False

    def test_invalid_base64_rejected(self):
        from security.file_scanner import scan_base64_payload
        v = scan_base64_payload("not-valid-base64!!!", filename="bad.pdf")
        assert v.safe is False
        assert any("invalid_base64" in t for t in v.threats)

    def test_sanitize_filename_traversal(self):
        from security.file_scanner import sanitize_filename
        assert ".." not in sanitize_filename("../../etc/passwd")
        assert "/" not in sanitize_filename("../../etc/passwd")

    def test_sanitize_filename_null_bytes(self):
        from security.file_scanner import sanitize_filename
        result = sanitize_filename("file\x00.txt")
        assert "\x00" not in result

    def test_sanitize_filename_empty(self):
        from security.file_scanner import sanitize_filename
        assert sanitize_filename("") == "unnamed_upload"

    def test_allowed_extension_check(self):
        from security.file_scanner import is_allowed_extension
        assert is_allowed_extension(".pdf") is True
        assert is_allowed_extension(".jpg") is True
        assert is_allowed_extension(".exe") is False
        assert is_allowed_extension(".bat") is False

    def test_quarantine_file(self, tmp_path, monkeypatch):
        from security.file_scanner import quarantine_file, get_quarantine_log
        monkeypatch.setenv("PHINS_QUARANTINE_DIR", str(tmp_path))
        import security.file_scanner as fs
        fs.QUARANTINE_DIR = str(tmp_path)

        path = quarantine_file(
            b"MZ evil content",
            filename="virus.exe",
            reason="executable detected",
            client_ip="1.2.3.4",
        )
        assert os.path.exists(path)
        log = get_quarantine_log()
        assert len(log) >= 1
        assert log[-1]["filename"] == "virus.exe"

    def test_javascript_in_file_blocked(self):
        from security.file_scanner import scan_file_bytes
        data = b"<iframe src='http://evil.com'></iframe>"
        v = scan_file_bytes(data, filename="page.html")
        assert v.safe is False


# ═══════════════════════════════════════════════════════════════════════════
# FIREWALL
# ═══════════════════════════════════════════════════════════════════════════

class TestFirewall:
    """Tests for security.firewall."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        from security.firewall import reset_firewall
        reset_firewall()
        yield
        reset_firewall()

    def test_clean_request_passes(self):
        from security.firewall import check_request
        v = check_request("192.168.1.100", path="/api/customers", method="GET")
        assert v.allowed is True

    def test_blocklist_blocks(self):
        from security.firewall import check_request, add_to_blocklist
        add_to_blocklist("10.0.0.99")
        v = check_request("10.0.0.99", path="/api/customers")
        assert v.allowed is False
        assert v.reason == "ip_blocklisted"

    def test_blocklist_cidr(self):
        from security.firewall import check_request, add_to_blocklist
        add_to_blocklist("10.20.0.0/16")
        v = check_request("10.20.5.5", path="/")
        assert v.allowed is False

    def test_allowlist_overrides(self):
        from security.firewall import check_request, add_to_blocklist, add_to_allowlist
        add_to_blocklist("10.0.0.99")
        add_to_allowlist("10.0.0.99")
        v = check_request("10.0.0.99", path="/")
        assert v.allowed is True

    def test_remove_from_blocklist(self):
        from security.firewall import check_request, add_to_blocklist, remove_from_blocklist
        add_to_blocklist("10.0.0.99")
        remove_from_blocklist("10.0.0.99")
        v = check_request("10.0.0.99", path="/")
        assert v.allowed is True

    def test_suspicious_user_agent_flagged(self):
        from security.firewall import check_request
        v = check_request("10.0.0.1", user_agent="sqlmap/1.5")
        assert "suspicious_user_agent" in v.signals

    def test_common_api_clients_not_flagged_as_suspicious(self):
        from security.firewall import check_request

        requests_verdict = check_request(
            "10.0.0.2", user_agent="python-requests/2.32.3"
        )
        curl_verdict = check_request("10.0.0.3", user_agent="curl/8.7.1")

        assert "suspicious_user_agent" not in requests_verdict.signals
        assert "suspicious_user_agent" not in curl_verdict.signals

    def test_directory_scan_detected(self):
        from security.firewall import check_request
        v = check_request("10.0.0.1", path="/.env")
        assert "directory_scan" in v.signals

    def test_threat_score_accumulation(self):
        from security.firewall import record_threat_signal, get_threat_score
        for _ in range(5):
            record_threat_signal("10.0.0.50", "sql_injection")
        score = get_threat_score("10.0.0.50")
        assert score > 0

    def test_request_fingerprint(self):
        from security.firewall import compute_request_fingerprint, detect_replay
        fp = compute_request_fingerprint("10.0.0.1", "/api/login", "POST", "Mozilla", 100)
        assert len(fp) == 16
        assert detect_replay("10.0.0.1", fp) is False

    def test_replay_detected(self):
        from security.firewall import compute_request_fingerprint, detect_replay
        for _ in range(10):
            fp = compute_request_fingerprint("10.0.0.1", "/api/login", "POST", "Mozilla", 100)
        assert detect_replay("10.0.0.1", fp, window=5) is True

    def test_connection_flood_flagged(self):
        from security.firewall import check_request
        import security.firewall as fw
        old = fw.BURST_MAX_CONNECTIONS
        fw.BURST_MAX_CONNECTIONS = 3
        try:
            for _ in range(5):
                v = check_request("10.0.0.77", path="/")
            assert "connection_flood" in v.signals
        finally:
            fw.BURST_MAX_CONNECTIONS = old

    def test_firewall_status_returns_data(self):
        from security.firewall import get_firewall_status, add_to_blocklist
        add_to_blocklist("1.2.3.4")
        status = get_firewall_status()
        assert "1.2.3.4" in status["blocklist_ips"]
        assert "config" in status

    def test_reset_clears_all(self):
        from security.firewall import add_to_blocklist, reset_firewall, get_firewall_status
        add_to_blocklist("5.5.5.5")
        reset_firewall()
        status = get_firewall_status()
        assert "5.5.5.5" not in status["blocklist_ips"]


# ═══════════════════════════════════════════════════════════════════════════
# REQUEST SANITIZER
# ═══════════════════════════════════════════════════════════════════════════

class TestRequestSanitizer:
    """Tests for security.request_sanitizer."""

    def test_clean_body_unchanged(self):
        from security.request_sanitizer import sanitize_request_body
        body = {"name": "Alice", "age": 30}
        result, warnings = sanitize_request_body(body)
        assert result["name"] == "Alice"
        assert result["age"] == 30
        assert len(warnings) == 0

    def test_script_tags_sanitized(self):
        from security.request_sanitizer import sanitize_request_body
        body = {"bio": "<script>alert('xss')</script>"}
        result, warnings = sanitize_request_body(body)
        assert "<script>" not in result["bio"]
        assert len(warnings) > 0

    def test_deeply_nested_rejected(self):
        from security.request_sanitizer import sanitize_request_body
        body: dict = {"a": {"b": {"c": {"d": {"e": "deep"}}}}}
        result, warnings = sanitize_request_body(body, max_depth=3)
        assert any("max depth" in w for w in warnings)

    def test_too_many_keys_truncated(self):
        from security.request_sanitizer import sanitize_request_body
        body = {f"key_{i}": i for i in range(100)}
        result, warnings = sanitize_request_body(body, max_keys=10)
        assert len(result) == 10
        assert any("keys exceeds" in w for w in warnings)

    def test_null_bytes_stripped(self):
        from security.request_sanitizer import sanitize_request_body
        body = {"name": "Alice\x00Bob"}
        result, _ = sanitize_request_body(body)
        assert "\x00" not in result["name"]

    def test_safe_json_loads_size_limit(self):
        from security.request_sanitizer import safe_json_loads
        big_json = json.dumps({"data": "x" * 10000})
        with pytest.raises(ValueError, match="too large"):
            safe_json_loads(big_json, max_size=100)

    def test_safe_json_loads_depth_limit(self):
        from security.request_sanitizer import safe_json_loads
        nested = {"a": {"b": {"c": {"d": {"e": {"f": {"g": 1}}}}}}}
        raw = json.dumps(nested)
        with pytest.raises(ValueError, match="too deep"):
            safe_json_loads(raw, max_depth=3)

    def test_safe_json_loads_normal(self):
        from security.request_sanitizer import safe_json_loads
        data = safe_json_loads('{"hello": "world"}')
        assert data == {"hello": "world"}

    def test_content_length_validation(self):
        from security.request_sanitizer import validate_content_length
        ok, _ = validate_content_length(100, 100)
        assert ok is True
        ok, msg = validate_content_length(100, 200)
        assert ok is False
        assert "mismatch" in msg

    def test_header_injection_prevention(self):
        from security.request_sanitizer import sanitize_header_value
        assert "\r" not in sanitize_header_value("value\r\nInjected: header")
        assert "\n" not in sanitize_header_value("value\r\nInjected: header")

    def test_csrf_token_roundtrip(self):
        from security.request_sanitizer import generate_csrf_token, validate_csrf_token
        token = generate_csrf_token("session123")
        ok, err = validate_csrf_token(token, "session123")
        assert ok is True
        assert err == ""

    def test_csrf_token_session_mismatch(self):
        from security.request_sanitizer import generate_csrf_token, validate_csrf_token
        token = generate_csrf_token("session123")
        ok, err = validate_csrf_token(token, "different_session")
        assert ok is False
        assert "mismatch" in err

    def test_csrf_token_tampered(self):
        from security.request_sanitizer import generate_csrf_token, validate_csrf_token
        token = generate_csrf_token("session123")
        tampered = token[:-5] + "XXXXX"
        ok, err = validate_csrf_token(tampered, "session123")
        assert ok is False

    def test_deep_sanitize_string(self):
        from security.request_sanitizer import deep_sanitize_string
        result = deep_sanitize_string("<script>alert(1)</script>")
        assert "<script>" not in result
        assert "&lt;" in result

    def test_iframe_tag_sanitized_in_body(self):
        from security.request_sanitizer import sanitize_request_body
        body = {"content": "<iframe src='evil.com'></iframe>"}
        result, warnings = sanitize_request_body(body)
        assert "<iframe" not in result["content"]

    def test_nested_list_sanitized(self):
        from security.request_sanitizer import sanitize_request_body
        body = {"items": [{"name": "<script>x</script>"}, "clean"]}
        result, warnings = sanitize_request_body(body)
        assert "<script>" not in str(result)


# ═══════════════════════════════════════════════════════════════════════════
# INTRUSION DETECTOR
# ═══════════════════════════════════════════════════════════════════════════

class TestIntrusionDetector:
    """Tests for security.intrusion_detector."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        from security.intrusion_detector import reset_ids
        reset_ids()
        yield
        reset_ids()

    def test_record_event(self):
        from security.intrusion_detector import record_event, get_recent_events, Severity
        record_event("test_event", severity=Severity.INFO, client_ip="1.2.3.4")
        events = get_recent_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "test_event"

    def test_severity_filtering(self):
        from security.intrusion_detector import record_event, get_recent_events, Severity
        record_event("info_event", severity=Severity.INFO, client_ip="1.2.3.4")
        record_event("critical_event", severity=Severity.CRITICAL, client_ip="1.2.3.4")
        critical = get_recent_events(severity=Severity.CRITICAL)
        assert len(critical) == 1
        assert critical[0]["event_type"] == "critical_event"

    def test_ip_filtering(self):
        from security.intrusion_detector import record_event, get_recent_events, Severity
        record_event("ev1", severity=Severity.INFO, client_ip="1.1.1.1")
        record_event("ev2", severity=Severity.INFO, client_ip="2.2.2.2")
        filtered = get_recent_events(client_ip="1.1.1.1")
        assert len(filtered) == 1

    def test_failed_login_convenience(self):
        from security.intrusion_detector import record_failed_login, get_recent_events
        record_failed_login("10.0.0.1", "admin", "wrong password")
        events = get_recent_events()
        assert events[0]["event_type"] == "failed_login"

    def test_upload_threat_convenience(self):
        from security.intrusion_detector import record_upload_threat, get_recent_events
        record_upload_threat("10.0.0.1", "virus.exe", ("executable_header",))
        events = get_recent_events()
        assert events[0]["event_type"] == "malicious_upload"
        assert events[0]["severity"] == "critical"

    def test_session_anomaly_new_session(self):
        from security.intrusion_detector import check_session_anomaly
        result = check_session_anomaly("sess-001", "1.1.1.1", "Mozilla")
        assert result is None

    def test_session_anomaly_ip_change(self):
        from security.intrusion_detector import check_session_anomaly
        check_session_anomaly("sess-002", "1.1.1.1", "Mozilla")
        result = check_session_anomaly("sess-002", "9.9.9.9", "Mozilla")
        assert result is not None
        assert "ip_changed" in result

    def test_session_anomaly_ua_change(self):
        from security.intrusion_detector import check_session_anomaly
        check_session_anomaly("sess-003", "1.1.1.1", "Mozilla/5.0")
        result = check_session_anomaly("sess-003", "1.1.1.1", "curl/7.0")
        assert result is not None
        assert "user_agent_changed" in result

    def test_credential_stuffing_alert(self):
        from security.intrusion_detector import record_event, get_active_alerts, Severity
        import security.intrusion_detector as ids
        old_threshold = ids.CREDENTIAL_STUFFING_THRESHOLD
        ids.CREDENTIAL_STUFFING_THRESHOLD = 3
        try:
            for i in range(5):
                record_event(
                    "failed_login",
                    severity=Severity.WARNING,
                    client_ip="10.0.0.55",
                    details={"username": f"user_{i}"},
                )
            alerts = get_active_alerts()
            assert any(a["rule"] == "credential_stuffing" for a in alerts)
        finally:
            ids.CREDENTIAL_STUFFING_THRESHOLD = old_threshold

    def test_directory_enumeration_alert(self):
        from security.intrusion_detector import record_event, get_active_alerts, Severity
        import security.intrusion_detector as ids
        old_threshold = ids.DIRECTORY_ENUM_THRESHOLD
        ids.DIRECTORY_ENUM_THRESHOLD = 3
        try:
            for _ in range(5):
                record_event(
                    "directory_scan",
                    severity=Severity.WARNING,
                    client_ip="10.0.0.66",
                )
            alerts = get_active_alerts()
            assert any(a["rule"] == "directory_enumeration" for a in alerts)
        finally:
            ids.DIRECTORY_ENUM_THRESHOLD = old_threshold

    def test_acknowledge_alert(self):
        from security.intrusion_detector import record_event, get_active_alerts, acknowledge_alert, Severity
        import security.intrusion_detector as ids
        old_threshold = ids.CREDENTIAL_STUFFING_THRESHOLD
        ids.CREDENTIAL_STUFFING_THRESHOLD = 2
        try:
            for i in range(3):
                record_event(
                    "failed_login",
                    severity=Severity.WARNING,
                    client_ip="10.0.0.77",
                    details={"username": f"user_{i}"},
                )
            alerts = get_active_alerts()
            assert len(alerts) > 0
            ack_ok = acknowledge_alert(alerts[0]["alert_id"])
            assert ack_ok is True
            unacked = get_active_alerts(include_acknowledged=False)
            assert all(a["alert_id"] != alerts[0]["alert_id"] for a in unacked)
        finally:
            ids.CREDENTIAL_STUFFING_THRESHOLD = old_threshold

    def test_security_summary(self):
        from security.intrusion_detector import record_event, get_security_summary, Severity
        record_event("test", severity=Severity.INFO, client_ip="1.1.1.1")
        summary = get_security_summary()
        assert "total_events" in summary
        assert summary["total_events"] >= 1

    def test_event_listener(self):
        from security.intrusion_detector import record_event, register_event_listener, Severity
        received: list = []
        register_event_listener(lambda e: received.append(e))
        record_event("test", severity=Severity.INFO, client_ip="1.1.1.1")
        assert len(received) == 1

    def test_buffer_bounded(self):
        from security.intrusion_detector import record_event, get_recent_events, Severity
        import security.intrusion_detector as ids
        old_size = ids.EVENT_BUFFER_SIZE
        ids.EVENT_BUFFER_SIZE = 5
        try:
            for i in range(20):
                record_event("flood", severity=Severity.INFO, client_ip="1.1.1.1")
            events = get_recent_events(limit=100)
            assert len(events) <= 5
        finally:
            ids.EVENT_BUFFER_SIZE = old_size


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION: MODULES WORK TOGETHER
# ═══════════════════════════════════════════════════════════════════════════

class TestSecurityIntegration:
    """Cross-module integration tests."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        from security.firewall import reset_firewall
        from security.intrusion_detector import reset_ids
        reset_firewall()
        reset_ids()
        yield
        reset_firewall()
        reset_ids()

    def test_malicious_upload_triggers_firewall_and_ids(self):
        from security.file_scanner import scan_file_bytes
        from security.firewall import record_threat_signal, get_threat_score
        from security.intrusion_detector import record_upload_threat, get_recent_events

        data = b"MZ" + b"\x00" * 200
        verdict = scan_file_bytes(data, filename="evil.exe")
        assert not verdict.safe

        record_threat_signal("attacker_ip", "malicious_upload")
        score = get_threat_score("attacker_ip")
        assert score > 0

        record_upload_threat("attacker_ip", "evil.exe", verdict.threats)
        events = get_recent_events(event_type="malicious_upload")
        assert len(events) == 1

    def test_sanitizer_catches_xss_in_body(self):
        from security.request_sanitizer import sanitize_request_body

        body = {
            "first_name": "Alice",
            "bio": "<script>document.cookie</script>",
            "address": {"street": "<iframe src='evil'>"}
        }
        result, warnings = sanitize_request_body(body)
        assert "<script>" not in json.dumps(result)
        assert "<iframe" not in json.dumps(result)
        assert len(warnings) >= 2

    def test_firewall_blocklist_cidr_range(self):
        from security.firewall import add_to_blocklist, check_request

        add_to_blocklist("203.0.113.0/24")
        for last_octet in (1, 50, 100, 254):
            v = check_request(f"203.0.113.{last_octet}", path="/")
            assert not v.allowed

        v = check_request("203.0.114.1", path="/")
        assert v.allowed

    def test_ids_correlates_multiple_attacks(self):
        from security.intrusion_detector import record_event, get_active_alerts, Severity
        import security.intrusion_detector as ids

        old_threshold = ids.CREDENTIAL_STUFFING_THRESHOLD
        ids.CREDENTIAL_STUFFING_THRESHOLD = 3
        try:
            for i in range(5):
                record_event(
                    "failed_login",
                    severity=Severity.WARNING,
                    client_ip="10.0.0.88",
                    details={"username": f"victim_{i}"},
                )
            alerts = get_active_alerts()
            assert any(a["rule"] == "credential_stuffing" for a in alerts)
            stuffing_alert = next(a for a in alerts if a["rule"] == "credential_stuffing")
            assert stuffing_alert["source_ip"] == "10.0.0.88"
        finally:
            ids.CREDENTIAL_STUFFING_THRESHOLD = old_threshold


# ═══════════════════════════════════════════════════════════════════════════
# DASHBOARD API
# ═══════════════════════════════════════════════════════════════════════════

class TestCyberSecurityDashboardAPI:
    """Tests for the /api/security/dashboard endpoint."""

    BASE = os.environ.get("TEST_BASE_URL", "http://localhost:8000")

    def _login_admin(self):
        import urllib.request
        data = json.dumps({"username": "admin", "password": "admin123"}).encode()
        req = urllib.request.Request(
            f"{self.BASE}/api/login",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                body = json.loads(resp.read())
                return body.get("token")
        except Exception:
            return None

    def test_dashboard_requires_auth(self):
        import urllib.request
        import urllib.error
        req = urllib.request.Request(f"{self.BASE}/api/security/dashboard")
        try:
            urllib.request.urlopen(req)
            assert False, "Should have been rejected"
        except urllib.error.HTTPError as e:
            assert e.code in (401, 403)

    def test_dashboard_returns_all_sections(self):
        import urllib.request
        token = self._login_admin()
        if not token:
            pytest.skip("Could not obtain admin token")
        req = urllib.request.Request(
            f"{self.BASE}/api/security/dashboard",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())

        assert "ai_report" in data
        assert "threat_intel" in data
        assert "login_activity" in data
        assert "application_stats" in data
        assert "supplier_stats" in data
        assert "firewall" in data
        assert "ids_summary" in data
        assert "ids_alerts" in data
        assert "ids_events" in data
        assert "sessions" in data
        assert "system" in data
        assert "quarantine" in data

    def test_ai_report_structure(self):
        import urllib.request
        token = self._login_admin()
        if not token:
            pytest.skip("Could not obtain admin token")
        req = urllib.request.Request(
            f"{self.BASE}/api/security/dashboard",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())

        ai = data["ai_report"]
        assert "risk_level" in ai
        assert "risk_score" in ai
        assert "findings" in ai
        assert "recommendations" in ai
        assert "protections_active" in ai
        assert "summary" in ai
        assert ai["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert isinstance(ai["risk_score"], (int, float))
        assert 0 <= ai["risk_score"] <= 100

    def test_dashboard_system_flags(self):
        import urllib.request
        token = self._login_admin()
        if not token:
            pytest.skip("Could not obtain admin token")
        req = urllib.request.Request(
            f"{self.BASE}/api/security/dashboard",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())

        system = data["system"]
        assert "firewall_enabled" in system
        assert "file_scanner_enabled" in system
        assert "ids_enabled" in system
        assert "request_sanitizer_enabled" in system

    def test_acknowledge_endpoint(self):
        import urllib.request
        import urllib.error
        token = self._login_admin()
        if not token:
            pytest.skip("Could not obtain admin token")
        data = json.dumps({"alert_id": "NONEXISTENT"}).encode()
        req = urllib.request.Request(
            f"{self.BASE}/api/security/ids/acknowledge",
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = json.loads(e.read())
        assert body.get("success") is False or body.get("message") == "Alert not found"

    def test_dashboard_handles_none_dates_in_applications(self):
        """Regression: sorted() crashed when application dates were None."""
        import urllib.request
        import web_portal.server as portal

        token = self._login_admin()
        if not token:
            pytest.skip("Could not obtain admin token")

        portal.UNDERWRITING_APPLICATIONS['TEST-NONE'] = {
            'id': 'TEST-NONE',
            'customer_id': 'CUST-001',
            'status': 'pending',
            'submitted_at': None,
            'created_at': None,
            'coverage_type': 'health',
        }
        portal.UNDERWRITING_APPLICATIONS['TEST-GOOD'] = {
            'id': 'TEST-GOOD',
            'customer_id': 'CUST-002',
            'status': 'approved',
            'submitted_at': '2026-01-01T00:00:00',
            'coverage_type': 'life',
        }

        req = urllib.request.Request(
            f"{self.BASE}/api/security/dashboard",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())

        assert data.get("application_stats", {}).get("total_applications", 0) >= 2
        app_ids = [a['id'] for a in data['application_stats']['recent_applications']]
        assert 'TEST-NONE' in app_ids
        assert 'TEST-GOOD' in app_ids
