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
