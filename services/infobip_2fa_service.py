"""Infobip 2FA PIN API (application + SMS PIN send + verify).

Matches Infobip's documented 2FA flow:

1. ``POST /2fa/2/applications`` (or reuse a named application)
2. ``POST /2fa/2/applications/{id}/messages`` (SMS template with ``{{pin}}``)
3. ``POST /2fa/2/pin`` to send a generated PIN from ``ServiceSMS``
4. ``POST /2fa/2/pin/{pinId}/verify`` to check the user-entered PIN

Application/message IDs are resolved from env, then by listing existing
Infobip objects, then by creating them once per process. The API key and
base URL come from the shared Infobip credentials — never hardcoded.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("phins.infobip_2fa")

_DEFAULT_APP_NAME = "PHINS OTP"
_LEGACY_APP_NAMES = ("2fa test application",)

_lock = threading.Lock()
_cached_application_id: Optional[str] = None
_cached_message_id: Optional[str] = None


def reset_infobip_2fa_cache() -> None:
    """Drop process-local 2FA IDs (tests only)."""
    global _cached_application_id, _cached_message_id
    with _lock:
        _cached_application_id = None
        _cached_message_id = None


def infobip_2fa_enabled() -> bool:
    flag = str(os.environ.get("INFOBIP_2FA_ENABLED", "true")).strip().lower()
    return flag not in ("0", "false", "no", "off")


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _sender() -> str:
    return _env("INFOBIP_SMS_SENDER") or _env("INFOBIP_2FA_SENDER") or "ServiceSMS"


def _application_name() -> str:
    return _env("INFOBIP_2FA_APPLICATION_NAME") or _DEFAULT_APP_NAME


def _otp_expiry_seconds() -> int:
    """Local OTP TTL that ``verify_otp`` enforces before calling Infobip."""
    try:
        return max(60, int(os.environ.get("OTP_EXPIRY_SECONDS", "300")))
    except (TypeError, ValueError):
        return 300


def _pin_time_to_live() -> str:
    """Infobip ``pinTimeToLive`` aligned to the local OTP expiry."""
    return _env("INFOBIP_2FA_PIN_TTL") or f"{_otp_expiry_seconds() // 60}m"


def _default_message_text() -> str:
    """SMS template whose stated expiry matches the local OTP TTL."""
    minutes = _otp_expiry_seconds() // 60
    unit = "minute" if minutes == 1 else "minutes"
    return (
        "Your PHINS verification code is {{pin}}. "
        f"It expires in {minutes} {unit}. Never share this code."
    )


def _application_payload() -> Dict[str, Any]:
    """Body from Infobip's create-application example (PHINS-named)."""
    return {
        "name": _application_name(),
        "enabled": True,
        "configuration": {
            "pinAttempts": 10,
            "allowMultiplePinVerifications": True,
            "pinTimeToLive": _pin_time_to_live(),
            "verifyPinLimit": "1/3s",
            "sendPinPerApplicationLimit": "100/1d",
            "sendPinPerPhoneNumberLimit": "10/1d",
        },
    }


def _message_payload() -> Dict[str, Any]:
    return {
        "pinType": "NUMERIC",
        "pinLength": int(_env("INFOBIP_2FA_PIN_LENGTH") or "6"),
        "messageText": _env("INFOBIP_2FA_MESSAGE_TEXT") or _default_message_text(),
        "senderId": _sender(),
    }


def _digits_phone(phone: str) -> str:
    return re.sub(r"\D", "", str(phone or ""))


def _as_list(payload: Any, *keys: str) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _infobip_json(
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Tuple[Any, Optional[str]]:
    from services.notification_service import _infobip_credentials, validated_urlopen

    api_key, base_url, error = _infobip_credentials()
    if error:
        return None, error
    if not str(path).startswith("/"):
        path = f"/{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{base_url}{path}", data=data, method=method)
    req.add_header("Authorization", f"App {api_key}")
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with validated_urlopen(req, timeout=30, allowed_schemes=("https",)) as response:
            body = json.loads(response.read().decode("utf-8") or "null")
            if response.status not in (200, 201, 202):
                return body, f"Infobip 2FA unexpected status: {response.status}"
            return body, None
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode() if exc.fp else str(exc)
        logger.error("Infobip 2FA API error %s %s: %s", method, path, error_body)
        hint = ""
        if exc.code == 401:
            hint = " (check INFOBIP_API_KEY and INFOBIP_BASE_URL)"
        return None, f"Infobip 2FA error: {exc.code}{hint}"
    except Exception as exc:
        logger.error("Infobip 2FA request failed %s %s: %s", method, path, exc)
        return None, str(exc)


def _match_application(items: List[Dict[str, Any]]) -> Optional[str]:
    wanted = {_application_name().lower(), *(name.lower() for name in _LEGACY_APP_NAMES)}
    for item in items:
        name = str(item.get("name") or "").strip().lower()
        app_id = str(item.get("applicationId") or item.get("id") or "").strip()
        if name in wanted and app_id:
            return app_id
    for item in items:
        app_id = str(item.get("applicationId") or item.get("id") or "").strip()
        if app_id and item.get("enabled", True):
            return app_id
    return None


def _match_message(items: List[Dict[str, Any]]) -> Optional[str]:
    sender = _sender().lower()
    for item in items:
        message_id = str(item.get("messageId") or item.get("id") or "").strip()
        text = str(item.get("messageText") or "")
        item_sender = str(item.get("senderId") or "").strip().lower()
        if message_id and "{{pin}}" in text and (not item_sender or item_sender == sender):
            return message_id
    # A template without ``{{pin}}`` will not inject the PIN, producing an SMS
    # with no code. Never reuse one — return None so a correct template is
    # created instead.
    return None


def ensure_2fa_ids() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Return ``(applicationId, messageId, error)``, creating resources if needed."""
    global _cached_application_id, _cached_message_id
    env_app = _env("INFOBIP_2FA_APPLICATION_ID")
    env_msg = _env("INFOBIP_2FA_MESSAGE_ID")
    with _lock:
        app_id = env_app or _cached_application_id
        message_id = env_msg or _cached_message_id
        if app_id and message_id:
            _cached_application_id = app_id
            _cached_message_id = message_id
            return app_id, message_id, None

    if not app_id:
        listed, list_error = _infobip_json("GET", "/2fa/2/applications")
        if list_error:
            return None, None, list_error
        app_id = _match_application(_as_list(listed, "applications"))
        if not app_id:
            created, create_error = _infobip_json(
                "POST", "/2fa/2/applications", _application_payload()
            )
            if create_error:
                return None, None, create_error
            if isinstance(created, dict):
                app_id = str(created.get("applicationId") or created.get("id") or "").strip()
        if not app_id:
            return None, None, "Infobip 2FA application could not be resolved"

    if not message_id:
        listed, list_error = _infobip_json(
            "GET", f"/2fa/2/applications/{app_id}/messages"
        )
        if list_error:
            return None, None, list_error
        message_id = _match_message(_as_list(listed, "messages"))
        if not message_id:
            created, create_error = _infobip_json(
                "POST",
                f"/2fa/2/applications/{app_id}/messages",
                _message_payload(),
            )
            if create_error:
                return None, None, create_error
            if isinstance(created, dict):
                message_id = str(
                    created.get("messageId") or created.get("id") or ""
                ).strip()
        if not message_id:
            return None, None, "Infobip 2FA message template could not be resolved"

    with _lock:
        _cached_application_id = app_id
        _cached_message_id = message_id
    return app_id, message_id, None


def send_2fa_pin(phone: str, sender: Optional[str] = None) -> Tuple[bool, Optional[str], Optional[str]]:
    """Send an Infobip-generated PIN over SMS. Returns ``(ok, pin_id, error)``."""
    if not infobip_2fa_enabled():
        return False, None, "Infobip 2FA is disabled"
    destination = _digits_phone(phone)
    if not destination:
        return False, None, "Infobip 2FA: invalid phone number"
    app_id, message_id, error = ensure_2fa_ids()
    if error:
        return False, None, error
    payload = {
        "applicationId": app_id,
        "messageId": message_id,
        "from": sender or _sender(),
        "to": destination,
    }
    result, request_error = _infobip_json("POST", "/2fa/2/pin", payload)
    if request_error:
        return False, None, request_error
    if not isinstance(result, dict):
        return False, None, "Infobip 2FA send returned an empty body"
    sms_status = str(result.get("smsStatus") or "").upper()
    if sms_status == "MESSAGE_NOT_SENT":
        return False, None, "Infobip 2FA did not send the SMS"
    pin_id = str(result.get("pinId") or result.get("pin_id") or "").strip()
    if not pin_id:
        return False, None, "Infobip 2FA send did not return pinId"
    return True, pin_id, None


def verify_2fa_pin(pin_id: str, pin: str) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """Verify a user-entered PIN against Infobip. Returns ``(ok, error, details)``."""
    pin_id = str(pin_id or "").strip()
    pin_code = str(pin or "").strip()
    if not pin_id or not pin_code:
        return False, "Infobip 2FA verify requires pinId and pin", {}
    result, request_error = _infobip_json(
        "POST", f"/2fa/2/pin/{pin_id}/verify", {"pin": pin_code}
    )
    if request_error:
        return False, request_error, {}
    if not isinstance(result, dict):
        return False, "Infobip 2FA verify returned an empty body", {}
    verified = result.get("verified")
    if verified is True or str(verified).strip().lower() == "true":
        return True, None, result
    remaining = result.get("attemptsRemaining")
    suffix = f" ({remaining} attempts remaining)" if remaining is not None else ""
    return False, f"Infobip 2FA PIN was not verified{suffix}", result
