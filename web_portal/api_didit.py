"""PHINS HTTP API for Didit standalone (server-to-server) identity checks.

Business logic lives in ``services/didit_service.py``. This module validates
staff sessions, scans uploaded images, and shapes JSON responses.

Routes
------
GET  /api/didit/status
POST /api/didit/id-verification
POST /api/didit/poa
POST /api/didit/database-validation
POST /api/didit/document-ai
POST /api/didit/passive-liveness
POST /api/didit/face-match
POST /api/didit/face-search
POST /api/didit/age-estimation
POST /api/didit/aml
POST /api/didit/kyb/search
POST /api/didit/kyb/select
POST /api/didit/email/send
POST /api/didit/email/check
POST /api/didit/phone/send
POST /api/didit/phone/check

Authorization: staff roles only (admin / underwriter / claims / actuary /
analyst). Errors use ``{"error": "..."}``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from services.didit_service import (
    DiditConfigError,
    DiditRequestError,
    DiditResult,
    decode_file_input,
    get_didit_service,
)

logger = logging.getLogger("phins.didit.api")

_STAFF_ROLES = {
    "admin",
    "underwriter",
    "actuary",
    "analyst",
    "claims",
    "claims_agent",
    "claims_manager",
    "underwriting_admin",
    "compliance",
    "founder",
}

_FILE_FIELDS = {
    "front_image": ("front.jpg", "image/jpeg"),
    "back_image": ("back.jpg", "image/jpeg"),
    "document": ("document.pdf", "application/pdf"),
    "user_image": ("user.jpg", "image/jpeg"),
    "ref_image": ("ref.jpg", "image/jpeg"),
}


def _deny(status: int, message: str) -> Tuple[int, Dict[str, Any]]:
    return status, {"error": message}


def _require_staff(session: Optional[Dict[str, Any]]) -> Optional[Tuple[int, Dict[str, Any]]]:
    if not session:
        return _deny(401, "Authentication required")
    role = str(session.get("role") or "").strip().lower()
    if role not in _STAFF_ROLES:
        return _deny(403, "Staff role required")
    return None


def _scan_file_field(field_name: str, value: Any, client_ip: str) -> Optional[str]:
    """Return a threat summary when an uploaded file must be blocked."""
    if value in (None, ""):
        return None
    default_name, default_type = _FILE_FIELDS.get(
        field_name, (f"{field_name}.bin", "application/octet-stream")
    )
    try:
        filename, raw, _content_type = decode_file_input(
            value, field_name, default_name, default_type
        )
    except DiditRequestError as exc:
        return str(exc)
    try:
        from security.file_scanner import scan_file_bytes
    except ImportError:
        logger.warning("Didit upload scan unavailable; rejecting %s", field_name)
        return "security_scanner_unavailable"
    # Only treat the content type as "declared" when the caller actually
    # supplied one. Bare base64 strings and {filename, data} objects carry no
    # MIME type, so the field default (e.g. image/jpeg) would otherwise be
    # compared against a PNG/WebP/PDF magic byte and rejected as a mismatch.
    declared_type = ""
    if isinstance(value, dict):
        declared_type = str(
            value.get("content_type")
            or value.get("file_type")
            or value.get("mime_type")
            or ""
        ).strip()
    try:
        verdict = scan_file_bytes(
            raw,
            filename=filename,
            declared_content_type=declared_type,
        )
    except Exception as exc:
        logger.warning("Didit upload scan errored (rejecting %s): %s", field_name, exc)
        return "security_scan_failed"
    if getattr(verdict, "safe", False):
        return None
    threats = tuple(getattr(verdict, "threats", ()) or ())
    try:
        from security.intrusion_detector import record_upload_threat
        record_upload_threat(client_ip or "didit", filename, threats)
    except Exception:
        pass
    return getattr(verdict, "threat_summary", None) or "; ".join(threats) or "file rejected"


def _scan_body_files(body: Dict[str, Any], names: Tuple[str, ...], client_ip: str) -> Optional[Tuple[int, Dict[str, Any]]]:
    for name in names:
        threat = _scan_file_field(name, body.get(name), client_ip)
        if threat:
            return _deny(400, f"File rejected by security scan: {threat}")
    return None


def _call(fn, **kwargs) -> Tuple[int, Dict[str, Any]]:
    try:
        result = fn(**kwargs)
    except DiditRequestError as exc:
        return _deny(400, str(exc))
    except DiditConfigError as exc:
        return _deny(503, str(exc))
    if not isinstance(result, DiditResult):
        return _deny(502, "Didit request failed")
    body = result.to_api_dict()
    if result.ok:
        return 200, body
    if "error" not in body:
        body["error"] = result.error or "Didit request failed"
    return result.status_code, body


def dispatch_get(
    path: str,
    session: Optional[Dict[str, Any]],
    query_params: Dict[str, Any],
    client_ip: str,
) -> Optional[Tuple[int, Dict[str, Any]]]:
    normalized = (path or "").rstrip("/") or "/"
    if not normalized.startswith("/api/didit"):
        return None
    denied = _require_staff(session)
    if denied:
        return denied
    if normalized in ("/api/didit", "/api/didit/status"):
        return 200, get_didit_service().status()
    return None


def dispatch_post(
    path: str,
    session: Optional[Dict[str, Any]],
    body_data: Dict[str, Any],
    client_ip: str,
    user_agent: str = "",
) -> Optional[Tuple[int, Dict[str, Any]]]:
    normalized = (path or "").rstrip("/") or "/"
    if not normalized.startswith("/api/didit"):
        return None
    denied = _require_staff(session)
    if denied:
        return denied

    body = body_data if isinstance(body_data, dict) else {}
    svc = get_didit_service()

    if normalized == "/api/didit/id-verification":
        scan = _scan_body_files(body, ("front_image", "back_image"), client_ip)
        if scan:
            return scan
        extras = {k: v for k, v in body.items() if k not in ("front_image", "back_image")}
        return _call(
            svc.id_verification,
            front_image=body.get("front_image"),
            back_image=body.get("back_image"),
            **extras,
        )

    if normalized == "/api/didit/poa":
        scan = _scan_body_files(body, ("document",), client_ip)
        if scan:
            return scan
        extras = {k: v for k, v in body.items() if k != "document"}
        return _call(svc.proof_of_address, document=body.get("document"), **extras)

    if normalized == "/api/didit/database-validation":
        return _call(svc.database_validation, **body)

    if normalized == "/api/didit/document-ai":
        scan = _scan_body_files(body, ("document",), client_ip)
        if scan:
            return scan
        extras = {k: v for k, v in body.items() if k not in ("document", "fields")}
        return _call(
            svc.document_ai,
            document=body.get("document"),
            fields=body.get("fields"),
            **extras,
        )

    if normalized == "/api/didit/passive-liveness":
        scan = _scan_body_files(body, ("user_image",), client_ip)
        if scan:
            return scan
        extras = {k: v for k, v in body.items() if k != "user_image"}
        return _call(svc.passive_liveness, user_image=body.get("user_image"), **extras)

    if normalized == "/api/didit/face-match":
        scan = _scan_body_files(body, ("user_image", "ref_image"), client_ip)
        if scan:
            return scan
        extras = {k: v for k, v in body.items() if k not in ("user_image", "ref_image")}
        return _call(
            svc.face_match,
            user_image=body.get("user_image"),
            ref_image=body.get("ref_image"),
            **extras,
        )

    if normalized == "/api/didit/face-search":
        scan = _scan_body_files(body, ("user_image",), client_ip)
        if scan:
            return scan
        extras = {k: v for k, v in body.items() if k != "user_image"}
        return _call(svc.face_search, user_image=body.get("user_image"), **extras)

    if normalized == "/api/didit/age-estimation":
        scan = _scan_body_files(body, ("user_image",), client_ip)
        if scan:
            return scan
        extras = {k: v for k, v in body.items() if k != "user_image"}
        return _call(svc.age_estimation, user_image=body.get("user_image"), **extras)

    if normalized == "/api/didit/aml":
        return _call(svc.aml, **body)

    if normalized == "/api/didit/kyb/search":
        return _call(svc.kyb_search, **body)

    if normalized == "/api/didit/kyb/select":
        extras = {k: v for k, v in body.items() if k != "kyb_response_id"}
        return _call(
            svc.kyb_select,
            kyb_response_id=str(body.get("kyb_response_id") or ""),
            **extras,
        )

    if normalized == "/api/didit/email/send":
        extras = {k: v for k, v in body.items() if k != "email"}
        return _call(svc.email_send, email=str(body.get("email") or ""), **extras)

    if normalized == "/api/didit/email/check":
        extras = {k: v for k, v in body.items() if k not in ("email", "code")}
        return _call(
            svc.email_check,
            email=str(body.get("email") or ""),
            code=str(body.get("code") or ""),
            **extras,
        )

    if normalized == "/api/didit/phone/send":
        extras = {k: v for k, v in body.items() if k not in ("phone", "channel")}
        return _call(
            svc.phone_send,
            phone=str(body.get("phone") or ""),
            channel=body.get("channel"),
            **extras,
        )

    if normalized == "/api/didit/phone/check":
        extras = {k: v for k, v in body.items() if k not in ("phone", "code")}
        return _call(
            svc.phone_check,
            phone=str(body.get("phone") or ""),
            code=str(body.get("code") or ""),
            **extras,
        )

    return None
