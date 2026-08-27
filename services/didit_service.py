"""Didit standalone verification client (server-to-server).

Calls ``https://verification.didit.me/v3/...`` with the application API key
in the ``x-api-key`` header. Hosted verification sessions are out of scope —
this module is for identity checks when PHINS already has images or structured
data.

Docs: https://docs.didit.me/api-reference/overview
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover - requests is in requirements.txt
    requests = None  # type: ignore
    REQUESTS_AVAILABLE = False


LOGGER = logging.getLogger("phins.didit")

DEFAULT_BASE_URL = "https://verification.didit.me"
DEFAULT_TIMEOUT_SECONDS = 30
FILE_TIMEOUT_SECONDS = 60
MAX_FILE_BYTES = int(os.environ.get("PHINS_MAX_UPLOAD_BYTES", 10 * 1024 * 1024))
DOCUMENT_AI_FIELD_MIN = 1
DOCUMENT_AI_FIELD_MAX = 30
DOCUMENT_AI_FIELD_TYPES = frozenset({"text", "number", "date"})

FileInput = Union[bytes, bytearray, str, Dict[str, Any]]
HttpPost = Callable[..., Any]


class DiditConfigError(RuntimeError):
    """Raised when the Didit client is not configured or cannot run."""


class DiditRequestError(ValueError):
    """Raised for invalid caller input before a Didit request is sent."""


@dataclass
class DiditResult:
    """Normalized Didit standalone API outcome."""

    ok: bool
    status_code: int
    request_id: Optional[str]
    payload: Dict[str, Any]
    error: Optional[str]
    endpoint: str
    retry_after: Optional[int] = None
    approved: Optional[bool] = None
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_api_dict(self) -> Dict[str, Any]:
        """JSON body for PHINS route handlers (plus the raw Didit payload)."""
        body: Dict[str, Any] = {
            "ok": self.ok,
            "request_id": self.request_id,
            "endpoint": self.endpoint,
        }
        if self.approved is not None:
            body["approved"] = self.approved
        if self.retry_after is not None:
            body["retry_after"] = self.retry_after
        if isinstance(self.payload, dict):
            for key, value in self.payload.items():
                if key not in body:
                    body[key] = value
        if self.error and not self.ok:
            body["error"] = self.error
        return body


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _strip_data_uri(value: str) -> str:
    text = (value or "").strip()
    if text.startswith("data:") and "," in text:
        return text.split(",", 1)[1]
    return text


def decode_file_input(
    value: FileInput,
    field_name: str,
    default_filename: str,
    default_content_type: str,
) -> Tuple[str, bytes, str]:
    """Normalize a PHINS file field into ``(filename, bytes, content_type)``."""
    if value is None:
        raise DiditRequestError(f"{field_name} is required")

    filename = default_filename
    content_type = default_content_type
    raw: Optional[bytes] = None

    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
    elif isinstance(value, dict):
        filename = str(
            value.get("filename")
            or value.get("file_name")
            or default_filename
        ).strip() or default_filename
        content_type = str(
            value.get("content_type")
            or value.get("file_type")
            or value.get("mime_type")
            or default_content_type
        ).strip() or default_content_type
        data = (
            value.get("data")
            or value.get("file_data")
            or value.get("file_data_b64")
            or value.get("content")
        )
        if isinstance(data, (bytes, bytearray)):
            raw = bytes(data)
        elif isinstance(data, str):
            raw = _b64_to_bytes(data, field_name)
        else:
            raise DiditRequestError(
                f"{field_name} must include base64 data, file_data, or content"
            )
    elif isinstance(value, str):
        raw = _b64_to_bytes(value, field_name)
    else:
        raise DiditRequestError(
            f"{field_name} must be a base64 string or {{filename, data}} object"
        )

    if not raw:
        raise DiditRequestError(f"{field_name} is empty")
    if len(raw) > MAX_FILE_BYTES:
        raise DiditRequestError(
            f"{field_name} exceeds the {MAX_FILE_BYTES} byte upload limit"
        )
    return filename, raw, content_type


def _b64_to_bytes(value: str, field_name: str) -> bytes:
    try:
        return base64.b64decode(_strip_data_uri(value), validate=False)
    except Exception as exc:
        raise DiditRequestError(f"{field_name} is not valid base64") from exc


def feature_approved(payload: Dict[str, Any], feature_key: str) -> Optional[bool]:
    """Return True/False when ``payload[feature_key].status`` is present."""
    block = payload.get(feature_key)
    if not isinstance(block, dict):
        return None
    status = str(block.get("status") or "").strip().lower()
    if not status:
        return None
    return status == "approved"


def _didit_error_message(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        for key in ("error", "detail", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, list) and value:
                return str(value[0])
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            return str(errors[0])
    if isinstance(payload, list) and payload:
        return str(payload[0])
    return fallback


def _as_form_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return str(value)


def _optional_bool(value: Any, default: Optional[bool] = None) -> Optional[bool]:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "on"):
        return True
    if text in ("0", "false", "no", "n", "off"):
        return False
    return default


class DiditService:
    """Thin Didit Verification API v3 client."""

    FEATURE_KEYS = (
        "id_verification",
        "poa",
        "database_validation",
        "document_ai",
        "passive_liveness",
        "face_match",
        "face_search",
        "age_estimation",
        "aml",
        "kyb_registry",
        "email",
        "phone",
    )

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
        file_timeout: Optional[int] = None,
        http_post: Optional[HttpPost] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.environ.get("DIDIT_API_KEY", "")).strip()
        self.base_url = (
            base_url
            or os.environ.get("DIDIT_BASE_URL", "")
            or DEFAULT_BASE_URL
        ).rstrip("/")
        self.timeout = timeout if timeout is not None else _env_int(
            "DIDIT_TIMEOUT", DEFAULT_TIMEOUT_SECONDS
        )
        self.file_timeout = file_timeout if file_timeout is not None else _env_int(
            "DIDIT_FILE_TIMEOUT", FILE_TIMEOUT_SECONDS
        )
        self._http_post = http_post
        self._enabled_override = enabled
        self.org_id = os.environ.get("DIDIT_ORG_ID", "").strip()
        self.application_id = os.environ.get("DIDIT_APPLICATION_ID", "").strip()
        self.client_id = os.environ.get("DIDIT_CLIENT_ID", "").strip()
        self.workflow_id = os.environ.get("DIDIT_WORKFLOW_ID", "").strip()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def is_enabled(self) -> bool:
        if self._enabled_override is not None:
            return bool(self._enabled_override) and self.is_configured()
        return _env_flag("DIDIT_ENABLED", default=True) and self.is_configured()

    def status(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "configured": self.is_configured(),
            "enabled": self.is_enabled(),
            "base_url": self.base_url,
            "org_id": self.org_id or None,
            "application_id": self.application_id or None,
            "client_id": self.client_id or None,
            "workflow_id": self.workflow_id or None,
            "endpoints": [
                "id-verification",
                "poa",
                "database-validation",
                "document-ai",
                "passive-liveness",
                "face-match",
                "face-search",
                "age-estimation",
                "aml",
                "kyb/search",
                "kyb/select",
                "email/send",
                "email/check",
                "phone/send",
                "phone/check",
            ],
        }

    def _require_ready(self) -> None:
        if not REQUESTS_AVAILABLE and self._http_post is None:
            raise DiditConfigError("The requests package is required for Didit")
        if not self.is_configured():
            raise DiditConfigError("Didit is not configured")
        if not self.is_enabled():
            raise DiditConfigError("Didit is disabled")

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def _headers(self, json_body: bool) -> Dict[str, str]:
        headers = {
            "x-api-key": self.api_key,
            "accept": "application/json",
        }
        if json_body:
            headers["content-type"] = "application/json"
        return headers

    def _post_json(self, path: str, body: Dict[str, Any], endpoint: str) -> DiditResult:
        self._require_ready()
        return self._send(
            path,
            endpoint=endpoint,
            json_body=body,
            timeout=self.timeout,
        )

    def _post_multipart(
        self,
        path: str,
        files: Dict[str, Tuple[str, bytes, str]],
        fields: Dict[str, Any],
        endpoint: str,
    ) -> DiditResult:
        self._require_ready()
        form_files = {
            name: (filename, BytesIO(content), content_type)
            for name, (filename, content, content_type) in files.items()
        }
        form_data = {
            key: _as_form_value(value)
            for key, value in fields.items()
            if value is not None
        }
        return self._send(
            path,
            endpoint=endpoint,
            files=form_files,
            data=form_data,
            timeout=self.file_timeout,
        )

    def _send(
        self,
        path: str,
        *,
        endpoint: str,
        json_body: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        timeout: int,
    ) -> DiditResult:
        url = self._url(path)
        headers = self._headers(json_body=json_body is not None)
        poster = self._http_post or requests.post
        try:
            response = poster(
                url,
                headers=headers,
                json=json_body,
                files=files,
                data=data,
                timeout=timeout,
            )
        except Exception as exc:
            LOGGER.warning("Didit %s request failed: %s", endpoint, exc)
            return DiditResult(
                ok=False,
                status_code=502,
                request_id=None,
                payload={},
                error="Didit request failed",
                endpoint=endpoint,
            )

        status_code = int(getattr(response, "status_code", 502) or 502)
        retry_after = _parse_retry_after(getattr(response, "headers", {}) or {})
        try:
            payload = response.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {"detail": payload}

        request_id = payload.get("request_id")
        if request_id is not None:
            request_id = str(request_id)

        if status_code >= 400:
            error = _didit_error_message(payload, _status_fallback(status_code))
            LOGGER.info(
                "Didit %s returned %s request_id=%s",
                endpoint,
                status_code,
                request_id or "-",
            )
            return DiditResult(
                ok=False,
                status_code=_map_http_status(status_code),
                request_id=request_id,
                payload=payload,
                error=error,
                endpoint=endpoint,
                retry_after=retry_after,
            )

        approved = None
        for key in self.FEATURE_KEYS:
            approved = feature_approved(payload, key)
            if approved is not None:
                break

        return DiditResult(
            ok=True,
            status_code=status_code,
            request_id=request_id,
            payload=payload,
            error=None,
            endpoint=endpoint,
            approved=approved,
        )

    def _common_fields(self, extras: Dict[str, Any]) -> Dict[str, Any]:
        fields: Dict[str, Any] = {}
        vendor_data = extras.pop("vendor_data", None)
        if vendor_data not in (None, ""):
            fields["vendor_data"] = str(vendor_data)
        save = _optional_bool(extras.pop("save_api_request", None), default=True)
        if save is not None:
            fields["save_api_request"] = save
        return fields

    # ------------------------------------------------------------------
    # Identity & documents
    # ------------------------------------------------------------------

    def id_verification(
        self,
        front_image: FileInput,
        back_image: Optional[FileInput] = None,
        **extras: Any,
    ) -> DiditResult:
        files = {
            "front_image": decode_file_input(
                front_image, "front_image", "front.jpg", "image/jpeg"
            ),
        }
        if back_image not in (None, ""):
            files["back_image"] = decode_file_input(
                back_image, "back_image", "back.jpg", "image/jpeg"
            )
        fields = self._common_fields(dict(extras))
        fields.update(extras)
        return self._post_multipart(
            "/v3/id-verification/", files, fields, "id-verification"
        )

    def proof_of_address(self, document: FileInput, **extras: Any) -> DiditResult:
        files = {
            "document": decode_file_input(
                document, "document", "poa.pdf", "application/pdf"
            ),
        }
        fields = self._common_fields(dict(extras))
        fields.update(extras)
        return self._post_multipart("/v3/poa/", files, fields, "poa")

    def database_validation(self, **fields: Any) -> DiditResult:
        payload = self._common_fields(dict(fields))
        payload.update(fields)
        missing = [
            key for key in (
                "issuing_state",
                "validation_type",
                "first_name",
                "last_name",
                "date_of_birth",
                "personal_number",
            )
            if not payload.get(key)
        ]
        if missing:
            raise DiditRequestError(
                "Missing required fields: " + ", ".join(missing)
            )
        return self._post_json(
            "/v3/database-validation/", payload, "database-validation"
        )

    def document_ai(
        self,
        document: FileInput,
        fields: Any,
        **extras: Any,
    ) -> DiditResult:
        files = {
            "document": decode_file_input(
                document, "document", "document.pdf", "application/pdf"
            ),
        }
        form = self._common_fields(dict(extras))
        form["fields"] = _encode_document_ai_fields(fields)
        first = extras.pop("expected_first_name", None)
        last = extras.pop("expected_last_name", None)
        company = extras.pop("expected_company_name", None)
        if first and last:
            form["expected_first_name"] = first
            form["expected_last_name"] = last
        elif company:
            form["expected_company_name"] = company
            country = extras.pop("expected_company_country", None)
            if country:
                form["expected_company_country"] = country
        else:
            raise DiditRequestError(
                "expected_first_name and expected_last_name, or expected_company_name, is required"
            )
        threshold = extras.pop("document_ai_name_match_score_threshold", None)
        if threshold is None:
            threshold = 80
        form["document_ai_name_match_score_threshold"] = threshold
        form.update(extras)
        return self._post_multipart("/v3/document-ai/", files, form, "document-ai")

    # ------------------------------------------------------------------
    # Biometrics
    # ------------------------------------------------------------------

    def passive_liveness(self, user_image: FileInput, **extras: Any) -> DiditResult:
        files = {
            "user_image": decode_file_input(
                user_image, "user_image", "user.jpg", "image/jpeg"
            ),
        }
        fields = self._common_fields(dict(extras))
        fields.update(extras)
        return self._post_multipart(
            "/v3/passive-liveness/", files, fields, "passive-liveness"
        )

    def face_match(
        self,
        user_image: FileInput,
        ref_image: FileInput,
        **extras: Any,
    ) -> DiditResult:
        files = {
            "user_image": decode_file_input(
                user_image, "user_image", "user.jpg", "image/jpeg"
            ),
            "ref_image": decode_file_input(
                ref_image, "ref_image", "ref.jpg", "image/jpeg"
            ),
        }
        fields = self._common_fields(dict(extras))
        fields.update(extras)
        return self._post_multipart("/v3/face-match/", files, fields, "face-match")

    def face_search(self, user_image: FileInput, **extras: Any) -> DiditResult:
        files = {
            "user_image": decode_file_input(
                user_image, "user_image", "user.jpg", "image/jpeg"
            ),
        }
        fields = self._common_fields(dict(extras))
        fields.update(extras)
        return self._post_multipart("/v3/face-search/", files, fields, "face-search")

    def age_estimation(self, user_image: FileInput, **extras: Any) -> DiditResult:
        files = {
            "user_image": decode_file_input(
                user_image, "user_image", "user.jpg", "image/jpeg"
            ),
        }
        fields = self._common_fields(dict(extras))
        fields.update(extras)
        return self._post_multipart(
            "/v3/age-estimation/", files, fields, "age-estimation"
        )

    # ------------------------------------------------------------------
    # Compliance / KYB / contact
    # ------------------------------------------------------------------

    def aml(self, **fields: Any) -> DiditResult:
        payload = self._common_fields(dict(fields))
        payload.update(fields)
        if not payload.get("full_name"):
            raise DiditRequestError("full_name is required")
        payload.setdefault("entity_type", "person")
        return self._post_json("/v3/aml/", payload, "aml")

    def kyb_search(self, **fields: Any) -> DiditResult:
        payload = self._common_fields(dict(fields))
        payload.update(fields)
        if not payload.get("country_code"):
            raise DiditRequestError("country_code is required")
        return self._post_json("/v3/kyb/search/", payload, "kyb/search")

    def kyb_select(self, kyb_response_id: str, **fields: Any) -> DiditResult:
        payload = self._common_fields(dict(fields))
        payload.update(fields)
        payload["kyb_response_id"] = kyb_response_id
        if not payload.get("kyb_response_id"):
            raise DiditRequestError("kyb_response_id is required")
        return self._post_json("/v3/kyb/select/", payload, "kyb/select")

    def email_send(self, email: str, **fields: Any) -> DiditResult:
        payload = self._common_fields(dict(fields))
        payload.update(fields)
        payload["email"] = (email or "").strip()
        if not payload["email"]:
            raise DiditRequestError("email is required")
        return self._post_json("/v3/email/send/", payload, "email/send")

    def email_check(self, email: str, code: str, **fields: Any) -> DiditResult:
        payload = self._common_fields(dict(fields))
        payload.update(fields)
        payload["email"] = (email or "").strip()
        payload["code"] = str(code or "").strip()
        if not payload["email"] or not payload["code"]:
            raise DiditRequestError("email and code are required")
        return self._post_json("/v3/email/check/", payload, "email/check")

    def phone_send(self, phone: str, channel: Optional[str] = None, **fields: Any) -> DiditResult:
        payload = self._common_fields(dict(fields))
        payload.update(fields)
        payload["phone"] = (phone or "").strip()
        if channel:
            payload["channel"] = channel
        if not payload["phone"]:
            raise DiditRequestError("phone is required")
        return self._post_json("/v3/phone/send/", payload, "phone/send")

    def phone_check(self, phone: str, code: str, **fields: Any) -> DiditResult:
        payload = self._common_fields(dict(fields))
        payload.update(fields)
        payload["phone"] = (phone or "").strip()
        payload["code"] = str(code or "").strip()
        if not payload["phone"] or not payload["code"]:
            raise DiditRequestError("phone and code are required")
        return self._post_json("/v3/phone/check/", payload, "phone/check")


def _encode_document_ai_fields(fields: Any) -> str:
    if isinstance(fields, str):
        try:
            parsed = json.loads(fields)
        except json.JSONDecodeError as exc:
            raise DiditRequestError("fields must be a JSON array") from exc
    else:
        parsed = fields
    if not isinstance(parsed, list):
        raise DiditRequestError("fields must be a JSON array of 1-30 items")
    if not (DOCUMENT_AI_FIELD_MIN <= len(parsed) <= DOCUMENT_AI_FIELD_MAX):
        raise DiditRequestError(
            f"fields must contain {DOCUMENT_AI_FIELD_MIN}-{DOCUMENT_AI_FIELD_MAX} items"
        )
    normalized: List[Dict[str, Any]] = []
    for index, item in enumerate(parsed):
        if not isinstance(item, dict):
            raise DiditRequestError(f"fields[{index}] must be an object")
        key = str(item.get("key") or "").strip()
        name = str(item.get("name") or "").strip()
        instruction = str(item.get("instruction") or "").strip()
        field_type = str(item.get("type") or "text").strip().lower()
        if not key or not name or not instruction:
            raise DiditRequestError(
                f"fields[{index}] requires key, name, and instruction"
            )
        if field_type not in DOCUMENT_AI_FIELD_TYPES:
            raise DiditRequestError(
                f"fields[{index}].type must be text, number, or date"
            )
        normalized.append({
            "key": key,
            "name": name,
            "instruction": instruction,
            "type": field_type,
            "required": bool(item.get("required", False)),
            "is_full_name": bool(item.get("is_full_name", False)),
        })
    return json.dumps(normalized, separators=(",", ":"), ensure_ascii=False)


def _parse_retry_after(headers: Any) -> Optional[int]:
    if not headers:
        return None
    raw = None
    try:
        raw = headers.get("Retry-After") or headers.get("retry-after")
    except Exception:
        raw = None
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _status_fallback(status_code: int) -> str:
    if status_code == 429:
        return "Didit rate limit exceeded"
    if status_code == 403:
        return "Didit rejected the request"
    if status_code >= 500:
        return "Didit service error"
    return "Didit request failed"


def _map_http_status(didit_status: int) -> int:
    if didit_status == 429:
        return 429
    if didit_status in (400, 404, 409, 422):
        return didit_status
    if didit_status in (401, 403):
        return 502
    if didit_status >= 500:
        return 502
    return didit_status


_SERVICE: Optional[DiditService] = None
_SERVICE_LOCK = threading.Lock()


def get_didit_service() -> DiditService:
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = DiditService()
        return _SERVICE


def reset_didit_service() -> None:
    global _SERVICE
    with _SERVICE_LOCK:
        _SERVICE = None


def set_didit_service_for_tests(service: Optional[DiditService]) -> None:
    global _SERVICE
    with _SERVICE_LOCK:
        _SERVICE = service


def public_status() -> Dict[str, Any]:
    return get_didit_service().status()
