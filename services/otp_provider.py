"""OTP delivery-provider switch: Infobip (PHINS-minted codes) vs Didit.

Infobip remains the notification/email/SMS pipe for welcome, billing, and
other templates. This module only affects one-time login/registration/
reset codes.

``OTP_PROVIDER=infobip`` (default)
    PHINS generates the code, hashes it, and Infobip/SMTP/Twilio delivers it.
    Verify compares the local hash.

``OTP_PROVIDER=didit``
    Didit generates and delivers the code (email / SMS / WhatsApp).
    Verify calls Didit ``/v3/email/check/`` or ``/v3/phone/check/``.
    Requires ``DIDIT_API_KEY``.
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

_PROVIDER_ALIASES = {
    "didit": "didit",
    "didit.me": "didit",
    "didit_me": "didit",
    "infobip": "infobip",
    "info_bip": "infobip",
    "info-bip": "infobip",
    "local": "infobip",
    "notification": "infobip",
    "notifications": "infobip",
}

_PHONE_CHANNELS = {"sms", "whatsapp", "telegram", "voice", "rcs"}


def resolve_otp_provider() -> str:
    """Return ``didit`` or ``infobip`` from ``OTP_PROVIDER`` (default Infobip)."""
    raw = str(os.environ.get("OTP_PROVIDER") or "").strip().lower()
    raw = raw.replace("-", "_").replace(" ", "_")
    if not raw:
        return "infobip"
    return _PROVIDER_ALIASES.get(raw, "infobip")


def is_didit_otp() -> bool:
    """True when login/registration/reset codes should go through Didit."""
    return resolve_otp_provider() == "didit"


def didit_phone_channel(delivery_channel: str) -> str:
    """Map a PHINS delivery channel to a Didit phone ``channel``."""
    channel = (delivery_channel or "").strip().lower()
    if channel == "whatsapp":
        return "whatsapp"
    override = str(os.environ.get("OTP_DIDIT_PHONE_CHANNEL") or "").strip().lower()
    if override in _PHONE_CHANNELS:
        return override
    return "sms"


def send_didit_otp(
    *,
    delivery_channel: str,
    email: Optional[str],
    phone: Optional[str],
    vendor_data: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """Ask Didit to send its own OTP. The PHINS-minted code is not used."""
    from services.didit_service import DiditConfigError, DiditRequestError, get_didit_service

    try:
        svc = get_didit_service()
    except Exception as exc:
        return False, f"Didit OTP unavailable: {exc}"
    if not svc.is_enabled():
        return False, "Didit is not configured (set DIDIT_API_KEY)"

    channel = (delivery_channel or "email").strip().lower()
    extras = {}
    if vendor_data:
        extras["vendor_data"] = str(vendor_data)

    email_ok = sms_ok = whatsapp_ok = False
    email_error = sms_error = whatsapp_error = None

    try:
        if channel in ("email", "both"):
            if not email:
                email_error = "Email address is required for Didit email OTP."
            else:
                result = svc.email_send(str(email), **extras)
                email_ok = bool(result.ok)
                email_error = None if email_ok else (result.error or "Didit email OTP send failed")

        if channel in ("sms", "both"):
            if not phone:
                sms_error = "Phone number is required for Didit SMS OTP."
            else:
                result = svc.phone_send(
                    str(phone),
                    channel=didit_phone_channel("sms"),
                    **extras,
                )
                sms_ok = bool(result.ok)
                sms_error = None if sms_ok else (result.error or "Didit SMS OTP send failed")

        if channel == "whatsapp":
            if not phone:
                return False, "A phone number is required for Didit WhatsApp OTP."
            result = svc.phone_send(str(phone), channel="whatsapp", **extras)
            whatsapp_ok = bool(result.ok)
            return (
                whatsapp_ok,
                None if whatsapp_ok else (result.error or "Didit WhatsApp OTP send failed"),
            )
    except (DiditConfigError, DiditRequestError) as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f"Didit OTP send failed: {exc}"

    if channel == "email":
        return email_ok, email_error
    if channel == "sms":
        return sms_ok, sms_error
    if email_ok or sms_ok:
        if email_ok and sms_ok:
            return True, None
        failed = sms_error if email_ok else email_error
        return True, (
            f"Verification code delivered via "
            f"{'email' if email_ok else 'sms'}; the other channel failed: "
            f"{failed or 'unknown error'}"
        )
    return False, "; ".join(
        part for part in (email_error, sms_error) if part
    ) or "Didit OTP send failed"


def verify_didit_otp(
    *,
    delivery_channel: str,
    email: Optional[str],
    phone: Optional[str],
    code: str,
) -> Tuple[bool, Optional[str]]:
    """Confirm a user-entered code with Didit."""
    from services.didit_service import DiditConfigError, DiditRequestError, get_didit_service

    code = str(code or "").strip()
    if not code:
        return False, "Verification code is required"

    try:
        svc = get_didit_service()
    except Exception as exc:
        return False, f"Didit OTP unavailable: {exc}"
    if not svc.is_enabled():
        return False, "Didit is not configured (set DIDIT_API_KEY)"

    channel = (delivery_channel or "email").strip().lower()

    def _accepted(result) -> Tuple[bool, Optional[str]]:
        if not result.ok:
            return False, result.error or "Invalid verification code"
        if result.approved is False:
            return False, "Invalid verification code"
        return True, None

    try:
        if channel in ("email", "both"):
            if email:
                ok, err = _accepted(svc.email_check(str(email), code))
                if ok or channel == "email":
                    return ok, err
        if channel in ("sms", "whatsapp", "both"):
            if not phone:
                return False, "Phone number is required for Didit phone OTP."
            return _accepted(svc.phone_check(str(phone), code))
        return False, "Unsupported Didit OTP channel"
    except (DiditConfigError, DiditRequestError) as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f"Didit OTP verify failed: {exc}"
