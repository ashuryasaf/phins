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


# ── backfill_status sanitises its error path ─────────────────────────────

class TestBackfillStatusErrorIsSanitised:
    """The `backfill_status` method is called from a GET endpoint reachable
    by every authenticated user. Any internal error from the document
    listing must surface as a generic message - never as ``str(exc)`` -
    so a hostile or unlucky caller cannot harvest filesystem paths or
    SQLAlchemy connection strings.
    """

    def test_backfill_status_returns_generic_error_on_failure(self, tmp_path, monkeypatch):
        from services.assessment_center_service import AssessmentCenterService
        from services.document_processing_service import DocumentProcessingService

        doc_svc = DocumentProcessingService(storage_root=str(tmp_path / "docs"))
        center = AssessmentCenterService(
            document_service=doc_svc,
            fact_store_dir=str(tmp_path / "facts"),
        )

        # Force the document service listing to raise an error containing
        # information that would normally be sensitive.
        def _boom(*_args, **_kwargs):
            raise RuntimeError(
                "could not connect to server: Connection refused "
                "Is the server running on host \"db.internal\" "
                "and accepting TCP/IP connections on port 5432? "
                "[file=/var/lib/phins/secrets.json]"
            )

        monkeypatch.setattr(doc_svc, "list_documents", _boom)

        result = center.backfill_status()
        assert result["error"] == "Document listing unavailable"
        # The original error string must not bleed into the response.
        assert "Connection refused" not in str(result)
        assert "5432" not in str(result)
        assert "/var/lib/phins" not in str(result)
        assert "db.internal" not in str(result)
        # Other counters remain valid even on failure.
        assert result["total_documents"] == 0
        assert result["with_facts"] == 0
        assert result["without_facts"] == 0


# ── backfill limit semantics: None means MAX, not DEFAULT ────────────────

class TestBackfillLimitSemantics:
    """Bugbot review flagged that ``limit=None`` was silently falling back
    to ``BACKFILL_DEFAULT_LIMIT`` (200), which was strictly fewer than an
    explicit ``limit=500``. ``limit=None`` now means "process as many as
    we can" up to ``BACKFILL_MAX_LIMIT`` (still bounded by the wall-clock
    time budget so the worker can't hang).
    """

    def test_none_limit_uses_max_not_default(self, tmp_path):
        from services.assessment_center_service import AssessmentCenterService
        from services.document_processing_service import DocumentProcessingService

        center = AssessmentCenterService(
            document_service=DocumentProcessingService(storage_root=str(tmp_path / "d")),
            fact_store_dir=str(tmp_path / "f"),
        )
        result = center.backfill_documents()
        assert result["limit_applied"] == center.BACKFILL_MAX_LIMIT

    def test_explicit_limit_is_clamped_to_max(self, tmp_path):
        from services.assessment_center_service import AssessmentCenterService
        from services.document_processing_service import DocumentProcessingService

        center = AssessmentCenterService(
            document_service=DocumentProcessingService(storage_root=str(tmp_path / "d")),
            fact_store_dir=str(tmp_path / "f"),
        )
        # 99999 must be clamped down to BACKFILL_MAX_LIMIT.
        result = center.backfill_documents(limit=99999)
        assert result["limit_applied"] == center.BACKFILL_MAX_LIMIT

    def test_invalid_limit_falls_back_to_default(self, tmp_path):
        from services.assessment_center_service import AssessmentCenterService
        from services.document_processing_service import DocumentProcessingService

        center = AssessmentCenterService(
            document_service=DocumentProcessingService(storage_root=str(tmp_path / "d")),
            fact_store_dir=str(tmp_path / "f"),
        )
        result = center.backfill_documents(limit="not-a-number")  # type: ignore[arg-type]
        assert result["limit_applied"] == center.BACKFILL_DEFAULT_LIMIT


# ── customer_id recovery for tokens that lost the claim ─────────────────

class TestCustomerIdRecovery:
    """Some session tokens were minted before the customer record was
    fully linked, or after a DB seed race. ``/api/session/validate``
    already runs a recovery chain that re-derives the customer_id from
    the username; the upload pipeline must do the same so the customer
    can immediately use the workbench instead of being told their
    'Customer session is invalid'.
    """

    def setup_method(self):
        from web_portal import api_assessment_center as mod
        from web_portal import server as portal
        self.mod = mod
        self.portal = portal
        self._snapshot = dict(portal.CUSTOMERS)
        portal.CUSTOMERS.clear()
        portal.CUSTOMERS["CUST-RECOVER-001"] = {
            "id": "CUST-RECOVER-001",
            "email": "lostid@example.com",
            "name": "Lost ID",
        }

    def teardown_method(self):
        self.portal.CUSTOMERS.clear()
        self.portal.CUSTOMERS.update(self._snapshot)

    def test_recovers_customer_id_from_username(self):
        session = {"role": "customer", "username": "lostid@example.com"}
        recovered = self.mod._recover_customer_id(session)
        assert recovered == "CUST-RECOVER-001"
        # Cached on the session so subsequent calls don't repeat the lookup.
        assert session.get("customer_id") == "CUST-RECOVER-001"

    def test_resolve_customer_uses_recovery_when_token_missing_id(self):
        session = {"role": "customer", "username": "lostid@example.com"}
        cust, err = self.mod._resolve_customer(session, "")
        assert err is None
        assert cust == "CUST-RECOVER-001"

    def test_me_endpoint_returns_recovered_customer_id(self):
        session = {"role": "customer", "username": "lostid@example.com"}
        status, body = self.mod.dispatch_get(
            "/api/assessment-center/me", session, {}, "127.0.0.1"
        )
        assert status == 200, body
        assert body["customer_id"] == "CUST-RECOVER-001"
        assert body["is_admin"] is False
        assert body["customer_id_recovered"] is True

    def test_me_endpoint_admin_role(self):
        session = {"role": "admin", "username": "admin"}
        status, body = self.mod.dispatch_get(
            "/api/assessment-center/me", session, {}, "127.0.0.1"
        )
        assert status == 200, body
        assert body["is_admin"] is True

    def test_me_endpoint_requires_authentication(self):
        status, body = self.mod.dispatch_get(
            "/api/assessment-center/me", None, {}, "127.0.0.1"
        )
        assert status == 401
        assert "error" in body


# ── _resolve_customer is forgiving of cosmetic differences ───────────────

class TestResolveCustomerIsForgiving:
    """Production logs showed customers occasionally hitting "Access denied"
    while uploading their own files because their stale URL or
    localStorage held the same customer_id in a slightly different form
    (lowercase, surrounding whitespace, etc.). The resolver must
    canonicalise both sides before comparing so a customer is never
    locked out of their own data; cross-tenant attempts must still be
    rejected with an actionable message.
    """

    def setup_method(self):
        from web_portal import api_assessment_center as mod
        self.mod = mod
        self.session = {"username": "asaf", "role": "customer", "customer_id": "CUST-ASAF-001"}

    def test_matches_session_customer_with_exact_value(self):
        cust, err = self.mod._resolve_customer(self.session, "CUST-ASAF-001")
        assert err is None
        assert cust == "CUST-ASAF-001"

    def test_matches_session_customer_case_insensitively(self):
        cust, err = self.mod._resolve_customer(self.session, "cust-asaf-001")
        assert err is None
        assert cust == "CUST-ASAF-001"

    def test_matches_session_customer_with_whitespace(self):
        cust, err = self.mod._resolve_customer(self.session, "  CUST-ASAF-001  ")
        assert err is None
        assert cust == "CUST-ASAF-001"

    def test_empty_request_uses_session_value(self):
        cust, err = self.mod._resolve_customer(self.session, "")
        assert err is None
        assert cust == "CUST-ASAF-001"

    def test_cross_tenant_request_rejected_with_actionable_message(self):
        cust, err = self.mod._resolve_customer(self.session, "CUST-OTHER-001")
        assert cust == ""
        assert err is not None
        # The message tells the customer exactly which account they ARE
        # signed in as so they can take action without trial and error.
        assert "CUST-ASAF-001" in err

    def test_admin_can_target_any_customer(self):
        admin = {"username": "admin", "role": "admin"}
        for target in ("CUST-X", "cust-y", " CUST-Z "):
            cust, err = self.mod._resolve_customer(admin, target)
            assert err is None
            # Whitespace is trimmed for admins too.
            assert cust.strip() == target.strip()

    def test_customer_session_with_no_customer_id_returns_invalid_session_error(self):
        cust, err = self.mod._resolve_customer({"role": "customer"}, "CUST-ANY")
        assert cust == ""
        assert err == "Customer session invalid - no customer_id"


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
