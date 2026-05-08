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
    Deterministic risk score derived from the unified fact store.
- ``GET  /api/assessment-center/customer/<id>/charts``
    Chart-ready data series for dashboards.
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
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


_ADMIN_ROLES = {"admin", "underwriter", "actuary", "analyst", "claims",
                "claims_agent", "claims_manager", "underwriting_admin"}


def _resolve_customer(session: Dict[str, Any], requested_customer_id: str) -> Tuple[str, Optional[str]]:
    """Return (customer_id, error). ``error`` is None on success."""
    if not session:
        return "", "Authentication required"
    role = str(session.get("role") or "").lower()
    session_customer = (
        session.get("customer_id")
        or (session.get("user") or {}).get("customer_id")
        or ""
    )
    requested = (requested_customer_id or "").strip()
    if role in _ADMIN_ROLES:
        return requested or session_customer or "", None
    if not session_customer:
        return "", "Customer session invalid - no customer_id"
    if requested and requested != session_customer:
        return "", "Access denied"
    return session_customer, None


def _service():
    from services.assessment_center_service import get_assessment_center
    return get_assessment_center()


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

    try:
        payload, mime, filename = _service().export_analysis(
            cust, analysis_type, export_format,
            document_ids=doc_ids, options=options,
        )
    except ValueError as exc:
        return _err(400, str(exc))
    except RuntimeError as exc:
        return _err(500, str(exc))
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

_UPLOAD_REGISTRY: Tuple[Dict[str, Any], ...] = (
    {
        "path": "/api/assessment-center/upload",
        "method": "POST",
        "module": "web_portal/api_assessment_center.py",
        "purpose": "Unified upload + assessment pipeline (recommended)",
        "assessment_center": True,
        "persistent": True,
    },
    {
        "path": "/api/assessment-center/customers",
        "method": "GET",
        "module": "web_portal/api_assessment_center.py",
        "purpose": "Admin: list customers with assessment facts",
        "assessment_center": True,
        "persistent": True,
    },
    {
        "path": "/api/assessment-center/backfill-status",
        "method": "GET",
        "module": "web_portal/api_assessment_center.py",
        "purpose": "How many existing documents still lack assessment facts",
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
        "path": "/api/assessment-center/customer/<id>/describe",
        "method": "GET",
        "module": "web_portal/api_assessment_center.py",
        "purpose": "Describe-data-with-data view organized by relevance category",
        "assessment_center": True,
        "persistent": True,
    },
    {
        "path": "/api/assessment-center/customer/<id>/documents",
        "method": "GET",
        "module": "web_portal/api_assessment_center.py",
        "purpose": "Documents owned by the customer with per-doc fact counts",
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
    return {
        "endpoints": list(_UPLOAD_REGISTRY),
        "count": len(_UPLOAD_REGISTRY),
        "assessment_center_canonical": "/api/assessment-center/upload",
        "notes": [
            "Routes marked 'delegated' already persist via DocumentProcessingService.",
            "Routes marked 'supersede' are kept for compatibility but should "
            "be migrated to the unified Assessment Center pipeline.",
            "External clearinghouses (Mislaka) push their rows as facts; the "
            "Assessment Center is the only place that performs aggregation.",
        ],
    }


# ── Dispatchers ───────────────────────────────────────────────────────────────

def dispatch_get(path: str, session: Dict[str, Any], query_params: Dict[str, Any],
                 client_ip: str) -> Optional[Tuple[int, Dict[str, Any]]]:
    if path == "/api/assessment-center/health":
        # Public, lightweight liveness probe that confirms the service can
        # construct its singleton without touching disk-heavy code paths. The
        # Railway healthcheck on /api/health stays the source of truth for
        # the whole portal; this is for the platform/operations dashboards
        # that want a per-feature ping.
        try:
            svc = _service()
            with svc._lock:  # noqa: SLF001 - intentional internal check
                customer_count = len(svc._facts)  # noqa: SLF001
            return 200, {
                "ok": True,
                "fact_store_dir": svc._fact_store_dir,  # noqa: SLF001
                "customers_in_memory": customer_count,
                "ts": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            }
        except Exception as exc:
            logger.exception("assessment-center health check failed: %s", exc)
            return 500, {"ok": False, "error": str(exc)}

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
            return 500, {"error": "Assessment center error", "details": str(exc)}

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
            return 500, {"error": "Assessment center error", "details": str(exc)}

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
            return 200, svc.compute_risk_indicators(cust)
        if resource == "charts":
            return 200, svc.build_chart_data(cust)
        if resource == "describe":
            doc_ids = None
            if isinstance(query_params, dict):
                qp = query_params.get("document_ids") or query_params.get("doc_ids")
                if isinstance(qp, list):
                    qp = qp[0] if qp else None
                if qp:
                    doc_ids = [d.strip() for d in str(qp).split(",") if d.strip()]
            return 200, svc.describe_data_with_data(cust, doc_ids)
        if resource == "documents":
            try:
                listing = svc.document_service.list_documents(
                    customer_id=cust, page=1, page_size=200,
                )
            except Exception as exc:
                return 500, {"error": "Document listing failed", "details": str(exc)}
            items = listing.get("items", []) if isinstance(listing, dict) else []
            doc_summaries = svc.get_document_assessments([
                (d.get("id") if isinstance(d, dict) else getattr(d, "id", None))
                for d in items
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
                })
            return 200, {"customer_id": cust, "items": enriched, "total": len(enriched)}
        if resource == "export":
            return 200, svc.export_customer_pack(cust)
    except Exception as exc:
        logger.exception("assessment-center GET failed for %s/%s: %s", cust, resource, exc)
        return 500, {"error": "Assessment center error", "details": str(exc)}

    return None


def dispatch_post(path: str, session: Dict[str, Any], body_data: Dict[str, Any],
                  client_ip: str, user_agent: str = "") -> Optional[Tuple[int, Dict[str, Any]]]:
    if not path.startswith("/api/assessment-center/"):
        return None

    if not session:
        return 401, {"error": "Authentication required"}

    body = body_data or {}
    svc = _service()
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
            from services.mislaka_report_generator import link_to_assessment_center

            mislaka = get_mislaka_service()
            product_value = str(body.get("product_type") or "all").lower()
            try:
                product_type = MislakaProductType(product_value)
            except ValueError:
                product_type = MislakaProductType.ALL
            result = mislaka.get_person_policies(id_number, product_type)
            payload = link_to_assessment_center(result, customer_id=cust or id_number)
            return 200, {
                "linked": True,
                "policies_received": len(result.policies),
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
                limit_value = int(limit_raw) if limit_raw not in (None, "", 0) else None
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

            try:
                result = svc.backfill_documents(
                    customer_id=requested_customer,
                    force=force,
                    limit=limit_value,
                )
            except Exception as exc:
                logger.exception("assessment-center backfill failed: %s", exc)
                return 500, {"error": "Backfill failed", "details": str(exc)}

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
            try:
                return 200, svc.run_analysis(
                    cust, analysis_type,
                    document_ids=doc_ids, options=options,
                )
            except ValueError as exc:
                return 400, {"error": str(exc)}

        if path == "/api/assessment-center/import":
            pack = body.get("pack")
            if not isinstance(pack, dict):
                return 400, {"error": "pack object required"}

            requested_customer = str(pack.get("customer_id") or "").strip()
            cust, err = _resolve_customer(session, requested_customer)
            if err:
                return 403, {"error": err}
            if not cust:
                return 400, {"error": "pack.customer_id required"}

            result = svc.import_customer_pack(pack, customer_id_override=cust)
            return 200, result
    except ValueError as exc:
        return 400, {"error": str(exc)}
    except Exception as exc:
        logger.exception("assessment-center POST failed for %s: %s", path, exc)
        return 500, {"error": "Assessment center error", "details": str(exc)}

    return None
