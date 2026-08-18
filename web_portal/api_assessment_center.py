"""
PHINS API extensions for the unified Assessment Center.

These dispatchers expose the
:class:`services.assessment_center_service.AssessmentCenterService` over HTTP
and are wired through the existing extension dispatcher in
``web_portal/server.py``.

Routes
------

GET endpoints
~~~~~~~~~~~~~
- ``GET  /api/assessment-center/upload-endpoints``
    Registry of every upload route on the platform plus whether each one is
    already routed through the Assessment Center.
- ``GET  /api/assessment-center/customer/<id>/profile``
    Customer 360 snapshot.
- ``GET  /api/assessment-center/customer/<id>/facts``
    Flat fact list (optional ``?fact_type=`` filter).
- ``GET  /api/assessment-center/customer/<id>/risk-indicators``
    Deterministic risk score derived from the unified fact store plus
    real platform signals (policies/claims/underwriting/billing) when available.
- ``GET  /api/assessment-center/customer/<id>/charts``
    Chart-ready data series for dashboards.
- ``GET  /api/assessment-center/customer/<id>/unified``
    Joined Customer 360 + risk + charts assessment payload.
- ``GET  /api/assessment-center/customer/<id>/export``
    Re-uploadable JSON pack of the customer's facts (with SHA-256 checksum).

POST endpoints
~~~~~~~~~~~~~~
- ``POST /api/assessment-center/upload``
    Persist a fresh upload and immediately mine facts into Customer 360.
- ``POST /api/assessment-center/scan``
    Re-run extraction on an already-stored document.
- ``POST /api/assessment-center/mislaka/link``
    Push a Mislaka query result into the Assessment Center as raw facts.
- ``POST /api/assessment-center/external-facts``
    Generic external fact ingestion (e.g. Swiftness, internal exports).
- ``POST /api/assessment-center/import``
    Re-import a previously exported customer pack.

Authorization is intentionally consistent with the rest of the platform:
- ``customer`` sessions can only read/write their own customer_id
- admin / underwriter / actuary / analyst / claims roles can read/write any
  customer record

Every response uses the platform's standard JSON envelope. Error payloads use
``{"error": "..."}`` so they match the rest of the API surface.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


_ADMIN_ROLES = {"admin", "underwriter", "actuary", "analyst", "claims",
                "claims_agent", "claims_manager", "underwriting_admin"}


_SYNTHETIC_CUSTOMER_PREFIX = "USER:"


# Scanner threats that always block an Assessment Center upload. Size and
# extension policy stay with DocumentProcessingService (its allow-list is
# broader - DICOM, HTML, media - and its size cap is authoritative), so only
# genuinely dangerous content categories are blocking here.
_BLOCKING_THREAT_PREFIXES = (
    "invalid_base64_encoding",
    "dangerous_extension",
    "double_extension_attack",
    "executable_header",
    "embedded_script",
    "macro_or_shell_signature",
    "null_byte_in_filename",
    "content_type_mismatch",
)


def _security_scan_upload(
    file_data_b64: str,
    file_name: str,
    declared_mime: str,
    client_ip: str,
) -> Optional[str]:
    """Scan an upload payload; return a threat summary when it must be blocked.

    Returns ``None`` when the payload is safe (or when the scanner is
    unavailable, preserving the platform's graceful-degradation convention).
    """
    try:
        from security.file_scanner import scan_base64_payload
    except ImportError:
        return None
    try:
        verdict = scan_base64_payload(
            file_data_b64,
            filename=file_name,
            declared_content_type=declared_mime or "",
            # Effectively defer size policy to DocumentProcessingService.
            max_size=1024 * 1024 * 1024,
        )
    except Exception as exc:  # pragma: no cover - scanner must never 500 uploads
        logger.warning("Assessment upload scan errored (allowing): %s", exc)
        return None
    blocking = [
        t for t in verdict.threats
        if t.startswith(_BLOCKING_THREAT_PREFIXES)
    ]
    if not blocking:
        return None
    try:
        from security.intrusion_detector import record_upload_threat
        record_upload_threat(client_ip, file_name, tuple(blocking))
    except Exception:
        pass
    return "; ".join(blocking)


def _synthetic_customer_id(username: str) -> str:
    """Return a stable synthetic customer_id derived from a username.

    A non-admin user must always be able to use the Assessment
    Workbench - to upload, mine, and review their own data - even
    when no formal customer record has been linked to their account
    yet. Without this fallback the workbench would refuse every
    upload with "Pick a customer first" and the user would see 0%
    success.

    The synthetic id is:
      - prefixed (``USER:``) so it can never collide with a real
        customer id (which use prefixes like ``CUST-`` or ``COM``);
      - lowercased + whitespace-stripped so the same user always
        resolves to the same bucket regardless of capitalisation;
      - safe to migrate later: an admin can move the facts from
        ``USER:asaf@assurance.co.il`` to ``CUST-ASAF-001`` once the
        formal record exists, since every fact carries the source
        document SHA-256 for provenance.
    """
    cleaned = re.sub(r"\s+", "", str(username or "")).strip().lower()
    if not cleaned:
        return ""
    return f"{_SYNTHETIC_CUSTOMER_PREFIX}{cleaned}"


def _recover_customer_id(session: Dict[str, Any]) -> str:
    """Best-effort recovery of the customer_id when the session token
    lost it (older tokens, DB seed race, etc.).

    Recovery chain (all are best-effort and fall through on failure):
      1. Match ``username`` (case-insensitive email) against the
         in-memory ``CUSTOMERS`` dict.
      2. Same against ``REGISTERED_CUSTOMERS``.
      3. Same against ``DatabaseManager.customers.get_by_email``.
      4. Synthesize a stable ``USER:<username>`` id so the workbench
         is *always* usable for an authenticated user, even when no
         formal customer record exists yet.

    The recovered value is written back to the in-memory session dict
    so subsequent calls in the same request thread see it without
    paying the lookup cost again.
    """
    if not session:
        return ""
    username = (session.get("username")
                or (session.get("user") or {}).get("username")
                or "").strip()
    if not username:
        return ""

    recovered = ""
    try:
        from web_portal import server as portal
    except Exception:
        portal = None  # type: ignore[assignment]

    if portal is not None:
        for store_name in ("CUSTOMERS", "REGISTERED_CUSTOMERS"):
            store = getattr(portal, store_name, None)
            if not isinstance(store, dict):
                continue
            for cid, cust in store.items():
                if not isinstance(cust, dict):
                    continue
                email = (cust.get("email") or "").strip().lower()
                if email and email == username.lower():
                    recovered = str(cid)
                    break
            if recovered:
                break

    if not recovered:
        # Only consult the database when it is explicitly enabled; the
        # test harness runs with USE_DATABASE=false and trying to open a
        # real connection there can hang for the full request budget.
        use_db = str(os.environ.get("USE_DATABASE", "")).lower() in ("true", "1", "yes")
        if use_db:
            try:
                from database.manager import DatabaseManager  # type: ignore
                with DatabaseManager() as db:
                    row = db.customers.get_by_email(username.lower())
                    if row is not None:
                        recovered = str(getattr(row, "id", "") or "")
            except Exception as exc:
                logger.debug("DB recovery for customer_id failed: %s", exc)

    if not recovered:
        # Final fallback: synthesise a stable id so the workbench is
        # never deadlocked on missing customer records. The admin tile
        # surfaces these synthetic users separately so they can be
        # migrated to formal customer records later.
        recovered = _synthetic_customer_id(username)

    if recovered:
        try:
            session["customer_id"] = recovered
        except Exception:
            pass
    return recovered


def _normalise_customer_id(value: Any) -> str:
    """Return a comparable customer_id (trim + uppercase + collapse whitespace).

    Production logs showed customers occasionally hitting "Access denied"
    when uploading their own files because their stale localStorage
    session, a URL param like ``?customer_id=cust-asaf-001`` (lower
    case) or a copy/paste with leading whitespace produced an ID that
    only differed cosmetically from the canonical value held by the
    server (``CUST-ASAF-001``). The session token is the source of
    truth for the customer's identity, so we just compare canonical
    forms here instead of failing fast on cosmetic differences.
    """
    if value is None:
        return ""
    return re.sub(r"\s+", "", str(value)).strip().upper()


def _resolve_customer(session: Dict[str, Any], requested_customer_id: str) -> Tuple[str, Optional[str]]:
    """Return (customer_id, error). ``error`` is None on success.

    Comparison is case-insensitive and whitespace-tolerant so a customer
    cannot lock themselves out of their own data via a stale URL or
    localStorage value. Admin roles can target any customer.
    """
    if not session:
        return "", "Authentication required"
    role = str(session.get("role") or "").lower()
    session_customer_raw = (
        session.get("customer_id")
        or (session.get("user") or {}).get("customer_id")
        or ""
    )
    session_customer = str(session_customer_raw or "").strip()
    requested_raw = str(requested_customer_id or "").strip()

    if role in _ADMIN_ROLES:
        # Admins can target any customer. We still trim cosmetic
        # whitespace from the input for a friendlier experience.
        return requested_raw or session_customer or "", None

    if not session_customer:
        # The token may have been minted before the customer was linked
        # (older tokens, race during seed). _recover_customer_id always
        # returns a stable id (real one if found, synthetic USER:<email>
        # otherwise) so the workbench is never deadlocked on missing
        # customer records.
        recovered = _recover_customer_id(session)
        if recovered:
            session_customer = recovered
        else:
            return "", "Customer session invalid - no username"

    if requested_raw:
        if _normalise_customer_id(requested_raw) != _normalise_customer_id(session_customer):
            logger.warning(
                "_resolve_customer: rejecting cross-tenant request from %s for %r",
                session.get("username") or session.get("user", {}).get("username") or "?",
                requested_raw,
            )
            return "", (
                f"You can only upload to your own account ({session_customer}). "
                "Refresh the page if you switched accounts."
            )

    # Always return the server's canonical customer_id, never the value
    # the caller sent, so downstream code never has to second-guess
    # which form to trust.
    return session_customer, None


def _service():
    from services.assessment_center_service import get_assessment_center
    return get_assessment_center()


def _gather_platform_context(customer_id: str) -> Dict[str, Any]:
    """Collect real in-memory platform rows owned by ``customer_id``.

    Returns an empty dict when the portal module is unavailable so risk
    scoring can still run on fact-store evidence alone. Never fabricates rows.
    """
    try:
        import web_portal.server as portal
    except Exception:
        return {}

    def _owned(rows):
        out = []
        for r in (rows or []):
            if isinstance(r, dict) and str(r.get("customer_id") or "") == str(customer_id):
                out.append(r)
        return out

    try:
        policies = _owned(list(getattr(portal, "POLICIES", {}).values()))
        claims = _owned(list(getattr(portal, "CLAIMS", {}).values()))
        uw = _owned(list(getattr(portal, "UNDERWRITING_APPLICATIONS", {}).values()))
        billing = _owned(list(getattr(portal, "BILLING", {}).values()))
    except Exception:
        return {}
    return {
        "policies": policies,
        "claims": claims,
        "underwriting": uw,
        "billing": billing,
    }


def _document_owner(svc, document_id: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Return ``(record, owner_customer_id)`` for ``document_id``.

    ``record`` is ``None`` when the document does not exist. ``owner`` is the
    canonical customer_id stored on the document record (preferring the
    explicit ``customer_id`` field, falling back to ``uploaded_by_customer``)
    or the empty string when neither is set. Errors are swallowed and surface
    as ``(None, "")`` so callers can decide between 404 and 500.
    """
    try:
        record = svc.document_service.get_document(document_id, include_data=False)
    except Exception as exc:
        logger.exception("document lookup failed for %s: %s", document_id, exc)
        return None, ""
    if not record or not isinstance(record, dict):
        return None, ""
    owner = (
        str(record.get("uploaded_by_customer") or "").strip()
        or str(record.get("customer_id") or "").strip()
    )
    return record, owner


def _ensure_documents_owned_by(
    svc,
    customer_id: str,
    document_ids: Optional[Iterable[str]],
    *,
    role: str,
) -> Tuple[bool, Optional[Tuple[int, Dict[str, str]]]]:
    """Verify every supplied ``document_id`` belongs to ``customer_id``.

    Returns ``(ok, error_tuple)``. ``error_tuple`` is ``None`` on success and
    otherwise ``(status_code, {"error": "..."})`` ready to return from the
    dispatcher. Admins bypass the check (they may legitimately operate on
    any customer's documents).

    SECURITY: Required to prevent IDOR on caller-supplied ``document_ids``.
    Even when downstream services intrinsically scope to ``customer_id``'s
    own facts (``describe_data_with_data`` and friends), failing fast here
    keeps every code path uniformly safe and avoids enumeration via the
    response shape.
    """
    if role in _ADMIN_ROLES:
        return True, None
    if not document_ids:
        return True, None
    for doc_id in document_ids:
        if not isinstance(doc_id, str) or not doc_id.strip():
            return False, (400, {"error": "Invalid document_id: must be a non-blank string"})
        record, owner = _document_owner(svc, doc_id.strip())
        if record is None:
            return False, (404, {"error": f"Document {doc_id} not found"})
        if _normalise_customer_id(owner) != _normalise_customer_id(customer_id):
            logger.warning(
                "cross-tenant document access rejected: doc=%s owner=%r requester=%s",
                doc_id, owner, customer_id,
            )
            return False, (403, {"error": "Document not accessible"})
    return True, None


def _policy_documents() -> Dict[str, Any]:
    """Return the live legacy POLICY_DOCUMENTS dict, or an empty dict.

    The legacy in-memory mirror sits inside ``web_portal.server`` so we
    import it lazily to avoid a circular dependency at module import time.
    Tests run without that import path available, so the helper degrades
    gracefully to an empty dict when the symbol is missing.
    """
    try:
        from web_portal import server as portal
    except Exception:
        return {}
    docs = getattr(portal, "POLICY_DOCUMENTS", None)
    return docs if isinstance(docs, dict) else {}


def _legacy_documents_pending(customer_id: Optional[str]) -> int:
    """Count legacy documents that have never been written to the doc service."""
    pending = 0
    for doc in _policy_documents().values():
        if not isinstance(doc, dict):
            continue
        if doc.get("persistent_doc_id"):
            continue
        if customer_id and doc.get("uploaded_by_customer") != customer_id:
            continue
        if doc.get("data") or doc.get("storage_path"):
            pending += 1
    return pending


def export_analysis_binary(
    *,
    session: Optional[Dict[str, Any]],
    body: Dict[str, Any],
) -> Tuple[int, Dict[str, str], bytes]:
    """Helper used by ``web_portal/server.py`` to stream binary exports.

    Returns ``(status_code, headers, body_bytes)``. The dispatcher in
    ``server.py`` calls this directly because the regular dispatcher path
    is JSON-only.
    """
    import json as _json

    def _err(status: int, message: str) -> Tuple[int, Dict[str, str], bytes]:
        payload = _json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        return status, {"Content-Type": "application/json", "Content-Length": str(len(payload))}, payload

    if not session:
        return _err(401, "Authentication required")
    requested_customer = str(body.get("customer_id") or "").strip()
    cust, err = _resolve_customer(session, requested_customer)
    if err:
        return _err(403, err)
    if not cust:
        return _err(400, "customer_id required")

    analysis_type = str(body.get("analysis_type") or "describe_data").strip()
    export_format = str(body.get("format") or "csv").strip().lower()
    doc_ids = body.get("document_ids") or None
    if doc_ids is not None and not isinstance(doc_ids, list):
        return _err(400, "document_ids must be a list")
    options = body.get("options") if isinstance(body.get("options"), dict) else {}

    svc = _service()
    role = str(session.get("role") or "").lower()

    # SECURITY: identical guard to /analysis - reject foreign document_ids
    # before they can flow into the export pipeline.
    ok, err_resp = _ensure_documents_owned_by(svc, cust, doc_ids, role=role)
    if not ok and err_resp is not None:
        status, body_dict = err_resp
        return _err(status, body_dict.get("error", "Document not accessible"))

    try:
        payload, mime, filename = svc.export_analysis(
            cust, analysis_type, export_format,
            document_ids=doc_ids, options=options,
        )
    except ValueError as exc:
        return _err(400, str(exc))
    except RuntimeError as exc:
        logger.exception("assessment-center export runtime error: %s", exc)
        return _err(500, "Export failed")
    except Exception as exc:
        logger.exception("assessment-center export failed: %s", exc)
        return _err(500, "Export failed")

    safe_name = re.sub(r'[^A-Za-z0-9._-]+', '_', filename) or "analysis.bin"
    return 200, {
        "Content-Type": mime,
        "Content-Disposition": f'attachment; filename="{safe_name}"',
        "Content-Length": str(len(payload)),
    }, payload


_BRIDGE_DEFAULT_LIMIT = 50
_BRIDGE_MAX_LIMIT = 200


def _bridge_legacy_documents(
    *,
    customer_id: Optional[str],
    limit: Optional[int],
) -> Dict[str, Any]:
    """Push legacy ``POLICY_DOCUMENTS`` into the doc service so backfill can mine them.

    Older uploads sometimes only landed in the in-memory ``POLICY_DOCUMENTS``
    mirror because the document service hadn't been wired into that route yet.
    This helper detects those cases, persists them through
    :class:`DocumentProcessingService` (so they get a SHA-256 envelope and
    survive restarts), tags them with ``persistent_doc_id`` for future runs,
    and returns the new IDs ready to be assessed.
    """
    bridged: List[str] = []
    errors: List[Dict[str, Any]] = []
    docs = _policy_documents()
    if not docs:
        return {"bridged": 0, "ids": [], "errors": []}

    try:
        from services.document_processing_service import get_document_service
        doc_svc = get_document_service()
    except Exception as exc:
        return {"bridged": 0, "ids": [], "errors": [{"error": f"doc_service_unavailable: {exc}"}]}

    # Always enforce a hard ceiling on how many legacy documents we'll
    # re-upload in a single request - rebuilding a 25MB file in memory per
    # entry adds up fast on Railway's small container budget.
    if limit is None:
        cap = _BRIDGE_DEFAULT_LIMIT
    else:
        try:
            cap = max(1, min(int(limit), _BRIDGE_MAX_LIMIT))
        except (TypeError, ValueError):
            cap = _BRIDGE_DEFAULT_LIMIT

    for legacy_id, doc in list(docs.items()):
        if len(bridged) >= cap:
            break
        if not isinstance(doc, dict):
            continue
        if doc.get("persistent_doc_id"):
            continue
        owner = doc.get("uploaded_by_customer") or doc.get("customer_id") or ""
        if customer_id and owner != customer_id:
            continue

        file_data_b64 = doc.get("data")
        if not file_data_b64:
            # Some legacy docs only have a storage_path; rebuild base64 from disk.
            storage_path = doc.get("storage_path")
            if storage_path:
                try:
                    import base64 as _b64
                    with open(storage_path, "rb") as fh:
                        file_data_b64 = _b64.b64encode(fh.read()).decode("ascii")
                except Exception as exc:
                    errors.append({"document_id": legacy_id, "error": f"read_failed: {exc}"})
                    continue
        if not file_data_b64:
            continue

        try:
            upload = doc_svc.upload_document(
                file_name=doc.get("name") or f"{legacy_id}.bin",
                file_data_b64=file_data_b64,
                mime_type=doc.get("type") or "application/octet-stream",
                entity_type=doc.get("entity_type"),
                entity_id=doc.get("entity_id"),
                document_type=doc.get("document_type"),
                description=doc.get("description"),
                customer_id=owner or None,
                uploaded_by=doc.get("uploaded_by") or "backfill",
                skip_processing=False,
            )
            doc["persistent_doc_id"] = upload.document_id
            doc["storage_path"] = upload.storage_path
            bridged.append(upload.document_id)
        except Exception as exc:
            errors.append({"document_id": legacy_id, "error": str(exc)})

    return {"bridged": len(bridged), "ids": bridged, "errors": errors}


# ── Upload endpoint registry ──────────────────────────────────────────────────
#
# This registry is the single source of truth for which upload endpoints the
# platform exposes and whether they have already been routed through the
# Assessment Center pipeline. It is returned as live JSON so dashboards never
# go stale relative to the codebase.

# Catalogue of every Assessment Center HTTP route plus the cross-platform
# upload routes that feed it. Originally named ``_UPLOAD_REGISTRY`` (only
# upload routes), it now includes the full Assessment Center surface so the
# workbench's discovery panel is accurate. The alias below preserves the
# old symbol for any external callers that may have imported it.
_API_REGISTRY: Tuple[Dict[str, Any], ...] = (
    {
        "path": "/api/assessment-center/upload",
        "method": "POST",
        "module": "web_portal/api_assessment_center.py",
        "purpose": "Unified upload + assessment pipeline (recommended)",
        "assessment_center": True,
        "persistent": True,
    },
    {
        "path": "/api/assessment-center/backfill",
        "method": "POST",
        "module": "web_portal/api_assessment_center.py",
        "purpose": "Re-run extraction on every previously uploaded document (admin)",
        "assessment_center": True,
        "persistent": True,
    },
    {
        "path": "/api/assessment-center/analysis",
        "method": "POST",
        "module": "web_portal/api_assessment_center.py",
        "purpose": "Run any analysis (customer_360 / risk / bi / describe / cross_document)",
        "assessment_center": True,
        "persistent": True,
    },
    {
        "path": "/api/assessment-center/export-file",
        "method": "POST",
        "module": "web_portal/api_assessment_center.py",
        "purpose": "Downloadable analysis report (CSV / XLSX / PDF)",
        "assessment_center": True,
        "persistent": True,
    },
    {
        "path": "/api/doc-service/upload",
        "method": "POST",
        "module": "web_portal/server.py",
        "purpose": "Persistent multi-file upload with processing",
        "assessment_center": "delegated",
        "persistent": True,
    },
    {
        "path": "/api/documents/upload",
        "method": "POST",
        "module": "web_portal/server.py",
        "purpose": "Insurance record upload (policy/claim/customer/underwriting)",
        "assessment_center": "delegated",
        "persistent": True,
    },
    {
        "path": "/api/documents/analyze",
        "method": "POST",
        "module": "web_portal/server.py",
        "purpose": "Legacy AI document analysis (medical/authority/receipt)",
        "assessment_center": "supersede",
        "persistent": True,
    },
    {
        "path": "/api/reports/upload",
        "method": "POST",
        "module": "web_portal/server.py",
        "purpose": "AI risk reports raw upload (CSV/PDF parsing)",
        "assessment_center": "supersede",
        "persistent": True,
    },
    {
        "path": "/api/risk-dashboard/upload",
        "method": "POST",
        "module": "web_portal/server.py",
        "purpose": "Risk dashboard ingestion",
        "assessment_center": "supersede",
        "persistent": True,
    },
    {
        "path": "/api/risk-assessment/upload",
        "method": "POST",
        "module": "web_portal/server.py",
        "purpose": "Risk assessment file ingestion",
        "assessment_center": "supersede",
        "persistent": True,
    },
    {
        "path": "/api/admin/actuarial-tables/upload",
        "method": "POST",
        "module": "web_portal/server.py",
        "purpose": "Actuarial table upload (admin)",
        "assessment_center": "supersede",
        "persistent": True,
    },
    {
        "path": "/api/admin/actuarial-tables/upload-file",
        "method": "POST",
        "module": "web_portal/server.py",
        "purpose": "Actuarial table file upload",
        "assessment_center": "supersede",
        "persistent": True,
    },
    {
        "path": "/api/admin/customers/upload",
        "method": "POST",
        "module": "web_portal/server.py",
        "purpose": "Bulk customer upload (admin)",
        "assessment_center": "supersede",
        "persistent": True,
    },
    {
        "path": "/api/contribution-documents/upload",
        "method": "POST",
        "module": "web_portal/api_extensions.py",
        "purpose": "Contribution document upload",
        "assessment_center": "supersede",
        "persistent": True,
    },
    {
        "path": "/api/media/upload",
        "method": "POST",
        "module": "web_portal/server.py",
        "purpose": "Binary multipart media upload",
        "assessment_center": False,
        "persistent": True,
    },
    {
        "path": "/api/mislaka/policies",
        "method": "POST",
        "module": "web_portal/server.py",
        "purpose": "Mislaka clearinghouse query (treated as facts, not analysis)",
        "assessment_center": "delegated",
        "persistent": True,
    },
)


def _registry_payload() -> Dict[str, Any]:
    upload_only = [e for e in _API_REGISTRY
                   if e.get("method") == "POST" and "upload" in (e.get("path") or "").lower()]
    return {
        "endpoints": list(_API_REGISTRY),
        "count": len(_API_REGISTRY),
        "upload_endpoints": upload_only,
        "upload_count": len(upload_only),
        "assessment_center_canonical": "/api/assessment-center/upload",
        "notes": [
            "Routes marked 'delegated' already persist via DocumentProcessingService.",
            "Routes marked 'supersede' are kept for compatibility but should "
            "be migrated to the unified Assessment Center pipeline.",
            "External clearinghouses (Mislaka) push their rows as facts; the "
            "Assessment Center is the only place that performs aggregation.",
            "'endpoints' includes the full Assessment Center API surface; "
            "'upload_endpoints' is the filtered POST-upload subset.",
        ],
    }


# Back-compat alias: external code (and older tests) imported ``_UPLOAD_REGISTRY``
# directly; keep the symbol pointing at the same tuple so nothing breaks.
_UPLOAD_REGISTRY = _API_REGISTRY


# ── Dispatchers ───────────────────────────────────────────────────────────────

def dispatch_get(path: str, session: Dict[str, Any], query_params: Dict[str, Any],
                 client_ip: str) -> Optional[Tuple[int, Dict[str, Any]]]:
    if path == "/api/assessment-center/health":
        # Public, lightweight liveness probe that confirms the service can
        # construct its singleton without touching disk-heavy code paths.
        #
        # SECURITY: this endpoint is intentionally unauthenticated (so
        # uptime monitors can poll it) and therefore must not leak any
        # information beyond a binary "is the feature alive" signal.
        # We previously exposed the absolute fact-store path and the live
        # customer-count - both were flagged as Medium-severity information
        # disclosure in the PR review, so the response is now reduced to
        # ``{"ok": True, "fact_store_writable": <bool>, "ts": <iso>}`` and
        # the error branch returns a generic message (full diagnostics are
        # already captured by ``logger.exception`` for operators).
        try:
            svc = _service()
            fact_store_writable = False
            try:
                fact_store_writable = bool(
                    os.path.isdir(svc._fact_store_dir)  # noqa: SLF001
                    and os.access(svc._fact_store_dir, os.W_OK)  # noqa: SLF001
                )
            except Exception:
                fact_store_writable = False
            return 200, {
                "ok": True,
                "fact_store_writable": fact_store_writable,
                "ts": datetime.utcnow().isoformat() + "Z",
            }
        except Exception as exc:
            logger.exception("assessment-center health check failed: %s", exc)
            return 500, {"ok": False, "error": "Health check failed"}

    if path == "/api/assessment-center/me":
        # Authoritative "who am I" for the workbench. Tells the front-end
        # the role, the canonical customer_id (after recovery), and
        # whether the caller has admin-level access. This is the only
        # source of truth the workbench should trust - localStorage and
        # URL params are discarded for non-admins.
        if not session:
            return 401, {"error": "Authentication required"}
        role = str(session.get("role") or "").lower()
        username = (session.get("username")
                    or (session.get("user") or {}).get("username")
                    or "")
        is_admin = role in _ADMIN_ROLES
        token_customer_id = str(session.get("customer_id") or "").strip()
        customer_id = token_customer_id
        if not customer_id and not is_admin:
            customer_id = _recover_customer_id(session)
        is_synthetic = bool(
            customer_id
            and customer_id.upper().startswith(_SYNTHETIC_CUSTOMER_PREFIX)
        )
        return 200, {
            "ok": True,
            "username": username,
            "role": role,
            "is_admin": is_admin,
            "customer_id": customer_id,
            "customer_id_recovered": bool(customer_id and not token_customer_id),
            "customer_id_is_synthetic": is_synthetic,
            # Friendly hint the workbench renders below the picker so the
            # customer always knows what they are operating on.
            "display_label": (
                username if is_synthetic else (customer_id or username)
            ),
        }

    if path == "/api/assessment-center/upload-endpoints":
        if not session:
            return 401, {"error": "Authentication required"}
        return 200, _registry_payload()

    if path == "/api/assessment-center/customers":
        if not session:
            return 401, {"error": "Authentication required"}
        role = str(session.get("role") or "").lower()
        if role not in _ADMIN_ROLES:
            return 403, {"error": "Admin role required"}
        try:
            rows = _service().list_customers_with_facts()
            return 200, {"items": rows, "total": len(rows)}
        except Exception as exc:
            logger.exception("assessment-center customers GET failed: %s", exc)
            return 500, {"error": "Assessment center error"}

    if path == "/api/assessment-center/records":
        if not session:
            return 401, {"error": "Authentication required"}
        role = str(session.get("role") or "").lower()

        def _qp(name: str) -> Optional[str]:
            if not isinstance(query_params, dict):
                return None
            val = query_params.get(name)
            if isinstance(val, list):
                val = val[0] if val else None
            return (str(val).strip() or None) if val is not None else None

        requested_customer = _qp("customer_id")
        if role in _ADMIN_ROLES:
            customer_filter = requested_customer
        else:
            # Customers can only ever see their own assessment records.
            own = (
                session.get("customer_id")
                or (session.get("user") or {}).get("customer_id")
                or ""
            )
            if not own:
                return 403, {"error": "Customer session invalid - no customer_id"}
            if requested_customer and requested_customer != own:
                return 403, {"error": "You can only view your own assessment records"}
            customer_filter = own

        try:
            from services.assessment_record_service import get_assessment_record_service
            svc_records = get_assessment_record_service()
            try:
                page = int(_qp("page") or 1)
            except ValueError:
                page = 1
            try:
                page_size = int(_qp("page_size") or 50)
            except ValueError:
                page_size = 50
            return 200, svc_records.list_records(
                customer_id=customer_filter,
                subject_type=_qp("subject_type"),
                subject_id=_qp("subject_id"),
                assessment_type=_qp("assessment_type"),
                page=page,
                page_size=page_size,
            )
        except Exception as exc:
            logger.exception("assessment-center records GET failed: %s", exc)
            return 500, {"error": "Assessment center error"}

    if path == "/api/assessment-center/records/summary":
        if not session:
            return 401, {"error": "Authentication required"}
        role = str(session.get("role") or "").lower()
        if role not in _ADMIN_ROLES:
            return 403, {"error": "Admin role required"}
        try:
            from services.assessment_record_service import get_assessment_record_service
            return 200, get_assessment_record_service().summary()
        except Exception as exc:
            logger.exception("assessment-center records summary failed: %s", exc)
            return 500, {"error": "Assessment center error"}

    if path == "/api/assessment-center/backfill-status":
        if not session:
            return 401, {"error": "Authentication required"}
        role = str(session.get("role") or "").lower()
        is_admin = role in _ADMIN_ROLES
        target_customer = None
        if not is_admin:
            target_customer = (
                session.get("customer_id")
                or (session.get("user") or {}).get("customer_id")
                or ""
            )
            if not target_customer:
                return 403, {"error": "Customer session invalid - no customer_id"}
        else:
            qp_customer = query_params.get("customer_id") if isinstance(query_params, dict) else None
            if isinstance(qp_customer, list):
                qp_customer = qp_customer[0] if qp_customer else None
            target_customer = (qp_customer or "").strip() or None

        legacy_pending = _legacy_documents_pending(target_customer)
        try:
            payload = _service().backfill_status(customer_id=target_customer)
            payload["legacy_pending"] = legacy_pending
            payload["pending_total"] = payload.get("without_facts", 0) + legacy_pending
            return 200, payload
        except Exception as exc:
            logger.exception("assessment-center backfill-status failed: %s", exc)
            return 500, {"error": "Assessment center error"}

    if not path.startswith("/api/assessment-center/customer/"):
        return None

    parts = path.split("/")
    # /api/assessment-center/customer/<id>/<resource>
    if len(parts) != 6:
        return None
    customer_id = parts[4]
    resource = parts[5]

    cust, err = _resolve_customer(session, customer_id)
    if err:
        return (401 if err == "Authentication required" else 403), {"error": err}
    if not cust:
        return 400, {"error": "customer_id required"}

    svc = _service()
    try:
        if resource == "profile":
            return 200, svc.build_customer_360(cust)
        if resource == "facts":
            fact_type = None
            if isinstance(query_params, dict):
                ft = query_params.get("fact_type")
                if isinstance(ft, list):
                    fact_type = ft[0] if ft else None
                else:
                    fact_type = ft
            return 200, {"customer_id": cust, "items": svc.get_facts(cust, fact_type)}
        if resource == "risk-indicators":
            platform_context = _gather_platform_context(cust)
            return 200, svc.compute_risk_indicators(
                cust, platform_context=platform_context or None,
            )
        if resource == "charts":
            platform_context = _gather_platform_context(cust)
            return 200, svc.build_chart_data(
                cust, platform_context=platform_context or None,
            )
        if resource == "unified":
            platform_context = _gather_platform_context(cust)
            return 200, svc.build_unified_assessment(
                cust, platform_context=platform_context or None,
            )
        if resource == "describe":
            doc_ids = None
            if isinstance(query_params, dict):
                qp = query_params.get("document_ids") or query_params.get("doc_ids")
                if isinstance(qp, list):
                    qp = qp[0] if qp else None
                if qp:
                    doc_ids = [d.strip() for d in str(qp).split(",") if d.strip()]
            # SECURITY: reject foreign document_ids before any service work.
            requester_role = str(session.get("role") or "").lower() if session else ""
            ok, err_resp = _ensure_documents_owned_by(svc, cust, doc_ids, role=requester_role)
            if not ok and err_resp is not None:
                return err_resp
            return 200, svc.describe_data_with_data(cust, doc_ids)
        if resource == "documents":
            try:
                listing = svc.document_service.list_documents(
                    customer_id=cust, page=1, page_size=200,
                )
            except Exception as exc:
                return 500, {"error": "Document listing failed"}
            items = listing.get("items", []) if isinstance(listing, dict) else []
            doc_summaries = svc.get_document_assessments([
                did for did in (
                    (d.get("id") if isinstance(d, dict) else getattr(d, "id", None))
                    for d in items
                ) if did
            ])
            enriched = []
            for d in items:
                rec = d if isinstance(d, dict) else {"id": getattr(d, "id", None)}
                doc_id = rec.get("id")
                summary = doc_summaries.get(doc_id, {})
                enriched.append({
                    "id": doc_id,
                    "name": rec.get("file_name") or rec.get("original_file_name") or doc_id,
                    "document_type": rec.get("document_type") or "general",
                    "category": rec.get("category") or "general",
                    "mime_type": rec.get("mime_type") or "",
                    "size": rec.get("file_size"),
                    "uploaded_at": rec.get("uploaded_date") or rec.get("uploaded_at") or rec.get("created_at"),
                    "sha256": rec.get("sha256_checksum") or rec.get("sha256"),
                    "facts_extracted": summary.get("facts_extracted", 0),
                    "by_type": summary.get("by_type", {}),
                    # Async pipeline visibility: queued | processing |
                    # completed | failed (None for legacy rows).
                    "processing_status": rec.get("processing_status"),
                    "status": rec.get("status"),
                })
            return 200, {"customer_id": cust, "items": enriched, "total": len(enriched)}
        if resource == "export":
            return 200, svc.export_customer_pack(cust)
    except Exception as exc:
        logger.exception("assessment-center GET failed for %s/%s: %s", cust, resource, exc)
        return 500, {"error": "Assessment center error"}

    return None


def dispatch_post(path: str, session: Dict[str, Any], body_data: Dict[str, Any],
                  client_ip: str, user_agent: str = "") -> Optional[Tuple[int, Dict[str, Any]]]:
    if not path.startswith("/api/assessment-center/"):
        return None

    if not session:
        return 401, {"error": "Authentication required"}

    body = body_data or {}
    role = str(session.get("role") or "").lower()

    try:
        if path == "/api/assessment-center/upload":
            file_name = str(body.get("file_name") or body.get("name") or "").strip()
            file_data_b64 = str(body.get("file_data_b64") or body.get("data") or "").strip()
            if not file_name or not file_data_b64:
                return 400, {"error": "file_name and file_data_b64 are required"}

            requested_customer = str(body.get("customer_id") or "").strip()
            cust, err = _resolve_customer(session, requested_customer)
            if err:
                return 403, {"error": err}

            threat_summary = _security_scan_upload(
                file_data_b64,
                file_name,
                str(body.get("mime_type") or ""),
                client_ip,
            )
            if threat_summary:
                return 400, {
                    "error": "File rejected by security scan",
                    "details": threat_summary,
                }

            svc = _service()
            assessment = svc.upload_and_assess(
                file_name=file_name,
                file_data_b64=file_data_b64,
                mime_type=body.get("mime_type"),
                category=body.get("category"),
                customer_id=cust or None,
                entity_type=body.get("entity_type"),
                entity_id=body.get("entity_id"),
                uploaded_by=session.get("username", "user"),
                uploaded_by_role=role,
                description=body.get("description"),
                source_context=body.get("source_context") or "assessment_upload",
            )
            return 201, assessment.to_dict()

        if path == "/api/assessment-center/scan":
            doc_id = str(body.get("document_id") or "").strip()
            if not doc_id:
                return 400, {"error": "document_id is required"}

            requested_customer = str(body.get("customer_id") or "").strip()
            cust, err = _resolve_customer(session, requested_customer)
            if err:
                return 403, {"error": err}

            svc = _service()

            # SECURITY: enforce document ownership before extraction. Without
            # this check any authenticated customer could pass another
            # customer's ``document_id`` and receive the extracted PII
            # (identity numbers, medical conditions, etc.) in the response,
            # plus have those facts persisted under the attacker's profile.
            # Admins legitimately scan on behalf of any customer.
            ok, err_resp = _ensure_documents_owned_by(svc, cust, [doc_id], role=role)
            if not ok and err_resp is not None:
                return err_resp

            assessment = svc.assess_document(
                doc_id,
                customer_id=cust or None,
                source_context=body.get("source_context") or "assessment_rescan",
            )
            return 200, assessment.to_dict()

        if path == "/api/assessment-center/mislaka/link":
            requested_customer = str(body.get("customer_id") or "").strip()
            cust, err = _resolve_customer(session, requested_customer)
            if err:
                return 403, {"error": err}

            id_number = str(body.get("id_number") or cust or "").strip()
            if not id_number.isdigit() or len(id_number) != 9:
                return 400, {"error": "Israeli ID number (9 digits) required"}

            from services.mislaka_api_service import (
                get_mislaka_service,
                MislakaProductType,
            )
            from services.mislaka_affiliations import ReportFilters
            from services.mislaka_report_generator import link_to_assessment_center

            mislaka = get_mislaka_service()
            product_value = str(body.get("product_type") or "all").lower()
            try:
                product_type = MislakaProductType(product_value)
            except ValueError:
                product_type = MislakaProductType.ALL
            result = mislaka.get_person_policies(id_number, product_type)
            # Adjustable reporting: optional filters narrow which real policy
            # rows are ingested as facts (policy number, status, provider, dates).
            report_filters = ReportFilters.from_dict(
                body.get("filters") if isinstance(body.get("filters"), dict) else None
            )
            payload = link_to_assessment_center(
                result, customer_id=cust or id_number, filters=report_filters,
            )
            return 200, {
                "linked": True,
                "policies_received": len(result.policies),
                "policies_linked": payload.get("summary", {}).get("fact_count_added")
                if isinstance(payload, dict) else None,
                "filters_applied": report_filters.to_dict(),
                "assessment": payload,
            }

        if path == "/api/assessment-center/external-facts":
            requested_customer = str(body.get("customer_id") or "").strip()
            cust, err = _resolve_customer(session, requested_customer)
            if err:
                return 403, {"error": err}
            if not cust:
                return 400, {"error": "customer_id required"}

            source = str(body.get("source") or "external").strip() or "external"
            fact_type = str(body.get("fact_type") or "external_policy").strip()
            records = body.get("records") or []
            if not isinstance(records, list):
                return 400, {"error": "records must be a list"}

            svc = _service()
            assessment = svc.ingest_external_facts(
                customer_id=cust,
                source=source,
                records=records,
                fact_type=fact_type,
            )
            return 200, assessment.to_dict()

        if path == "/api/assessment-center/backfill":
            if role not in _ADMIN_ROLES:
                return 403, {"error": "Admin role required"}
            requested_customer = str(body.get("customer_id") or "").strip() or None
            try:
                limit_raw = body.get("limit")
                limit_value = int(limit_raw) if limit_raw not in (None, "") else None
            except (TypeError, ValueError):
                return 400, {"error": "limit must be an integer"}
            force = bool(body.get("force"))
            include_legacy = body.get("include_legacy")
            if include_legacy is None:
                include_legacy = True
            include_legacy = bool(include_legacy)

            bridge_summary = (
                _bridge_legacy_documents(customer_id=requested_customer, limit=limit_value)
                if include_legacy
                else {"bridged": 0, "ids": [], "errors": []}
            )

            svc = _service()
            try:
                result = svc.backfill_documents(
                    customer_id=requested_customer,
                    force=force,
                    limit=limit_value,
                )
            except Exception as exc:
                logger.exception("assessment-center backfill failed: %s", exc)
                return 500, {"error": "Backfill failed"}

            return 200, {
                "success": True,
                "bridge": bridge_summary,
                "result": result,
                "customer_id": requested_customer or "all",
            }

        if path == "/api/assessment-center/analysis":
            requested_customer = str(body.get("customer_id") or "").strip()
            cust, err = _resolve_customer(session, requested_customer)
            if err:
                return 403, {"error": err}
            if not cust:
                return 400, {"error": "customer_id required"}
            analysis_type = str(body.get("analysis_type") or "customer_360").strip()
            doc_ids = body.get("document_ids") or None
            if doc_ids is not None and not isinstance(doc_ids, list):
                return 400, {"error": "document_ids must be a list"}
            options = body.get("options") if isinstance(body.get("options"), dict) else {}
            # Inject real platform rows for any analysis that returns risk.
            if "platform_context" not in options:
                options = dict(options)
                options["platform_context"] = _gather_platform_context(cust)
            svc = _service()

            # SECURITY: defense-in-depth. ``describe_data_with_data`` only
            # iterates the caller's own facts so a foreign ``document_id``
            # would already produce zero results, but failing fast keeps
            # every code path uniformly safe and forecloses future
            # regressions if the analysis pipeline gains new fact-loading
            # paths that aren't intrinsically customer-scoped.
            ok, err_resp = _ensure_documents_owned_by(svc, cust, doc_ids, role=role)
            if not ok and err_resp is not None:
                return err_resp

            try:
                return 200, svc.run_analysis(
                    cust, analysis_type,
                    document_ids=doc_ids, options=options,
                )
            except ValueError as exc:
                return 400, {"error": str(exc)}
            except Exception as exc:
                # Mirror the explicit catch-all used by /backfill so a
                # malformed document_ids entry, an unexpected data shape, or
                # any other surprise from the analysis pipeline returns a
                # structured 500 instead of a raw traceback. The full
                # exception is captured server-side by ``logger.exception``.
                logger.exception("assessment-center analysis failed for %s: %s", cust, exc)
                return 500, {"error": "Analysis failed"}

        if path == "/api/assessment-center/export-file":
            import base64 as _b64
            import json as _json
            status, headers_map, payload = export_analysis_binary(session=session, body=body)
            if status != 200:
                try:
                    return status, _json.loads(payload.decode("utf-8"))
                except Exception:
                    return status, {"error": "Export failed"}
            content_disp = headers_map.get("Content-Disposition", "")
            fname = ""
            if "filename=" in content_disp:
                fname = content_disp.split("filename=")[-1].strip('"')
            return 200, {
                "file_name": fname,
                "content_type": headers_map.get("Content-Type", "application/octet-stream"),
                "data_b64": _b64.b64encode(payload).decode("ascii"),
                "size": len(payload),
            }

        if path == "/api/assessment-center/import":
            # SECURITY: imports inject arbitrary facts (identity, medical,
            # insurance, savings) into the customer 360 / risk model, with
            # no per-fact provenance check beyond the pack's own SHA-256.
            # A non-admin caller importing a pack — even one scoped to
            # their own customer_id — could inflate or fabricate the
            # signals that downstream BI / actuarial / risk endpoints
            # consume. Match the gating already applied to
            # /api/assessment-center/backfill (also admin-only) so the
            # whole class of bulk-fact-mutation endpoints is uniformly
            # restricted.
            if role not in _ADMIN_ROLES:
                return 403, {"error": "Admin role required"}

            pack = body.get("pack")
            if not isinstance(pack, dict):
                return 400, {"error": "pack object required"}

            requested_customer = str(pack.get("customer_id") or "").strip()
            cust, err = _resolve_customer(session, requested_customer)
            if err:
                return 403, {"error": err}
            if not cust:
                return 400, {"error": "pack.customer_id required"}

            svc = _service()
            result = svc.import_customer_pack(pack, customer_id_override=cust)
            return 200, result
    except ValueError as exc:
        return 400, {"error": str(exc)}
    except Exception as exc:
        logger.exception("assessment-center POST failed for %s: %s", path, exc)
        return 500, {"error": "Assessment center error"}

    return None
