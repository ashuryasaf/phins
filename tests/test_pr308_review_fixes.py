"""
Regression tests for the security review fixes applied to PR #308.

The PR review flagged three issues on top of the polling-storm work:

1. ``/api/assessment-center/health`` was unauthenticated and leaked the
   absolute fact-store path plus the live customer count. The endpoint
   must now expose only ``{"ok", "fact_store_writable", "ts"}`` so
   uptime monitors can still poll without revealing internal state.

2. ``str(exc)`` was returned in 500 error payloads from several
   Assessment Center endpoints, which can leak filesystem paths,
   stack-trace hints or DB connection details. Generic 500 error
   responses must no longer carry the raw exception string.

3. ``/api/assessment-center/analysis`` only caught ``ValueError``;
   any other surprise from the analysis pipeline propagated up and
   confused callers. The endpoint must now also catch and report
   unexpected errors with a generic ``Analysis failed`` message.
"""

from __future__ import annotations

import os

import pytest
import requests

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8000")


def _admin_session():
    resp = requests.post(f"{BASE_URL}/api/login", json={
        "username": "admin",
        "password": "admin123",
    })
    if resp.status_code != 200:
        pytest.skip("Admin login failed - test server may not have users seeded")
    return {"Authorization": f"Bearer {resp.json().get('token')}"}


# ── Health endpoint ───────────────────────────────────────────────────────

class TestHealthEndpointDoesNotLeak:
    def test_health_response_is_minimal(self):
        # Public endpoint - no auth header attached on purpose.
        resp = requests.get(f"{BASE_URL}/api/assessment-center/health")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Only the new minimal keys are allowed.
        assert set(body.keys()) <= {"ok", "fact_store_writable", "ts"}
        assert body.get("ok") is True
        # The boolean flag is acceptable - the absolute path was the leak.
        assert isinstance(body.get("fact_store_writable"), bool)
        # Strings that previously leaked must not be present.
        assert "fact_store_dir" not in body
        assert "customers_in_memory" not in body
        # ts is a timestamp, not an error message.
        assert "/" not in str(body.get("ts", ""))


# ── Generic 500 error payloads ────────────────────────────────────────────

class TestErrorPayloadsAreSanitised:
    def test_admin_only_endpoint_reaches_clean_error_path(self):
        # Hitting /api/assessment-center/customers without auth produces a
        # generic 401 - confirms there is no debug payload on the auth path.
        resp = requests.get(f"{BASE_URL}/api/assessment-center/customers")
        assert resp.status_code == 401
        body = resp.json()
        # Generic message; must not include 'details' / 'Traceback' / etc.
        assert "error" in body
        assert "details" not in body or not body.get("details")

    def test_analysis_endpoint_handles_bad_request_cleanly(self):
        # Analysis with an unknown analysis_type returns a 400 with a clean
        # ValueError message (which is intended caller-friendly text), but
        # *not* a 500 leaking internals.
        headers = _admin_session()
        resp = requests.post(
            f"{BASE_URL}/api/assessment-center/analysis",
            json={
                "customer_id": "CUST-PR308",
                "analysis_type": "this-does-not-exist",
            },
            headers=headers,
        )
        assert resp.status_code == 400, resp.text
        body = resp.json()
        assert "error" in body
        # No traceback / module path in the response.
        assert "Traceback" not in str(body)
        assert "/workspace/" not in str(body)
        assert "site-packages" not in str(body)


# ── Catch-all on /analysis (mirrors /backfill style) ──────────────────────

class TestAnalysisCatchAll:
    def test_analysis_returns_400_for_invalid_document_ids(self):
        headers = _admin_session()
        resp = requests.post(
            f"{BASE_URL}/api/assessment-center/analysis",
            json={
                "customer_id": "CUST-PR308",
                "analysis_type": "describe_data",
                "document_ids": "not-a-list",
            },
            headers=headers,
        )
        assert resp.status_code == 400
        body = resp.json()
        assert "document_ids" in body.get("error", "")


# ── RuntimeError handler in export_analysis_binary ───────────────────────

class TestExportRuntimeErrorIsSanitised:
    """The PR review explicitly asked for the RuntimeError handler in
    ``export_analysis_binary`` to behave like the generic ``except
    Exception`` branch - log the trace server-side and return ``"Export
    failed"`` to the caller. This guards against a silent regression
    that would re-introduce ``str(exc)`` leakage if the openpyxl /
    reportlab stack ever raises a ``RuntimeError`` carrying a filesystem
    path or library internal.
    """

    def test_runtime_error_returns_generic_message(self, monkeypatch):
        from web_portal import api_assessment_center as mod

        class _StubService:
            def export_analysis(self, *_args, **_kwargs):
                raise RuntimeError("/tmp/openpyxl/internal_path leaked")

        monkeypatch.setattr(mod, "_service", lambda: _StubService())
        monkeypatch.setattr(mod, "_resolve_customer", lambda *_a, **_k: ("CUST-T", None))

        status, headers, body = mod.export_analysis_binary(
            session={"role": "admin", "username": "tester"},
            body={"customer_id": "CUST-T", "analysis_type": "describe_data", "format": "csv"},
        )
        assert status == 500
        assert headers.get("Content-Type") == "application/json"
        import json as _json
        payload = _json.loads(body.decode("utf-8"))
        # Generic message - no path, no library internals.
        assert payload == {"error": "Export failed"}, payload
        assert "openpyxl" not in body.decode("utf-8")
        assert "/tmp" not in body.decode("utf-8")

    def test_value_error_still_returns_caller_friendly_message(self, monkeypatch):
        # ValueError remains intentionally surfaced as a 400 with the raw
        # message because those texts are user-facing input validation
        # ("Unknown analysis_type: 'xyz'", "Unsupported export_format: 'wat'").
        from web_portal import api_assessment_center as mod

        class _StubService:
            def export_analysis(self, *_args, **_kwargs):
                raise ValueError("Unsupported export_format: 'wat'")

        monkeypatch.setattr(mod, "_service", lambda: _StubService())
        monkeypatch.setattr(mod, "_resolve_customer", lambda *_a, **_k: ("CUST-T", None))

        status, _headers, body = mod.export_analysis_binary(
            session={"role": "admin", "username": "tester"},
            body={"customer_id": "CUST-T", "analysis_type": "describe_data", "format": "wat"},
        )
        assert status == 400
        import json as _json
        assert "Unsupported export_format" in _json.loads(body.decode("utf-8"))["error"]


# ── /data fallback is gated against dev-system hijack ─────────────────────

class TestDataVolumeGate:
    """The bot review flagged that ``os.path.isdir('/data')`` could
    silently hijack persistence paths on dev machines that happened to
    have a ``/data`` directory. The ``_data_volume_eligible`` gate now
    requires either Railway env signals or an explicit opt-in.
    """

    def test_eligibility_requires_writable_dir_and_railway_or_opt_in(self, tmp_path, monkeypatch):
        from services.assessment_center_service import _data_volume_eligible

        # Clear every Railway / opt-in signal.
        for key in (
            "RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID",
            "RAILWAY_DEPLOYMENT_ID", "RAILWAY_STATIC_URL", "PHINS_USE_DATA_VOLUME",
        ):
            monkeypatch.delenv(key, raising=False)

        # A writable directory alone is not enough.
        assert _data_volume_eligible(str(tmp_path)) is False

        # With an explicit opt-in, the directory becomes eligible.
        monkeypatch.setenv("PHINS_USE_DATA_VOLUME", "1")
        assert _data_volume_eligible(str(tmp_path)) is True
        monkeypatch.delenv("PHINS_USE_DATA_VOLUME", raising=False)

        # Or with a Railway env signal.
        monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
        assert _data_volume_eligible(str(tmp_path)) is True

    def test_missing_directory_is_never_eligible(self, monkeypatch):
        from services.assessment_center_service import _data_volume_eligible

        monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
        assert _data_volume_eligible("/this/path/does/not/exist") is False


# ── Registry honesty (renamed _UPLOAD_REGISTRY -> _API_REGISTRY) ──────────

class TestRegistryPayloadShape:
    def test_registry_exposes_both_full_and_upload_subset(self):
        headers = _admin_session()
        resp = requests.get(
            f"{BASE_URL}/api/assessment-center/upload-endpoints",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Keys we now expose.
        assert "endpoints" in body
        assert "upload_endpoints" in body
        assert "count" in body and "upload_count" in body
        # The upload subset is a strict subset of the full catalogue and
        # contains only POST routes whose path mentions 'upload'.
        for route in body["upload_endpoints"]:
            assert route.get("method") == "POST"
            assert "upload" in route.get("path", "").lower()
        # Summary numbers are coherent.
        assert body["count"] >= body["upload_count"]
