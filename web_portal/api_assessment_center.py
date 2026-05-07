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
    if path == "/api/assessment-center/upload-endpoints":
        return 200, _registry_payload()

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

            pack["customer_id"] = cust
            return 200, svc.import_customer_pack(pack)
    except ValueError as exc:
        return 400, {"error": str(exc)}
    except Exception as exc:
        logger.exception("assessment-center POST failed for %s: %s", path, exc)
        return 500, {"error": "Assessment center error", "details": str(exc)}

    return None
