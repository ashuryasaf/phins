"""Application claim codes — "Track my application" quick registry.

When a chat application is submitted we mint a single-use **claim code** bound
to that application, its customer, and the email address the applicant already
proved they control (the chat flow OTP-verifies the email before any
underwriting question is answered).

The claim code lets the applicant open a short registry screen that is
pre-filled from their application and asks only for a password, then drops
them into their customer account.

Security model
--------------
* Only a **hash** of the code is stored, compared with ``compare_digest``.
* Codes are single-use and expire (default 14 days).
* A code is bound to ``application_id`` + ``customer_id`` + ``email``; the
  lookup must present the matching email.
* **A claim code can never set the password of an email that already has a
  login.** In that case the flow reports ``needs_login`` and the applicant must
  authenticate normally (or use password reset). This is what stops a leaked
  code from becoming an account takeover.
* Redemption is atomic under a lock so a code cannot be spent twice.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

CLAIM_CODE_PREFIX = "PHINS-CLAIM"
DEFAULT_TTL_DAYS = 14

# Status values returned by :meth:`ApplicationClaimService.lookup`.
STATUS_NEEDS_PASSWORD = "needs_password"
STATUS_NEEDS_LOGIN = "needs_login"


def _now() -> datetime:
    return datetime.now()


def _norm_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _hash_code(code: str) -> str:
    return hashlib.sha256(str(code or "").strip().upper().encode("utf-8")).hexdigest()


class ApplicationClaimService:
    """In-memory registry of single-use application claim codes."""

    def __init__(self, ttl_days: int = DEFAULT_TTL_DAYS) -> None:
        self._lock = threading.RLock()
        self._by_hash: Dict[str, Dict[str, Any]] = {}
        self._by_application: Dict[str, str] = {}
        self._ttl_days = int(ttl_days)

    # ------------------------------------------------------------------
    # issue
    # ------------------------------------------------------------------

    def issue(
        self,
        *,
        application_id: str,
        customer_id: str,
        email: str,
        policy_id: str = "",
        underwriting_id: str = "",
        customer_name: str = "",
        phone: str = "",
        summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Mint a claim code for a submitted application.

        Re-issuing for the same application invalidates the previous code so a
        single application never has two live claim codes.
        """
        application_id = str(application_id or "").strip()
        email_n = _norm_email(email)
        if not application_id or not email_n:
            return {"ok": False, "error": "application_id and email are required"}

        code = f"{CLAIM_CODE_PREFIX}-{secrets.token_hex(5).upper()}"
        code_hash = _hash_code(code)
        issued_at = _now()
        record = {
            "code_hash": code_hash,
            "application_id": application_id,
            "customer_id": str(customer_id or ""),
            "email": email_n,
            "policy_id": str(policy_id or ""),
            "underwriting_id": str(underwriting_id or ""),
            "customer_name": str(customer_name or ""),
            "phone": str(phone or ""),
            "summary": dict(summary or {}),
            "issued_at": issued_at.isoformat(),
            "expires_at": (issued_at + timedelta(days=self._ttl_days)).isoformat(),
            "status": "active",
            "used_at": None,
            "attempts": 0,
        }

        with self._lock:
            previous = self._by_application.get(application_id)
            if previous and previous in self._by_hash:
                self._by_hash[previous]["status"] = "superseded"
                del self._by_hash[previous]
            self._by_hash[code_hash] = record
            self._by_application[application_id] = code_hash

        return {
            "ok": True,
            "claim_code": code,
            "expires_at": record["expires_at"],
            "application_id": application_id,
        }

    # ------------------------------------------------------------------
    # resolve / lookup
    # ------------------------------------------------------------------

    def _resolve(self, claim_code: str, email: str) -> Dict[str, Any]:
        """Return the live record for a code+email pair, or an error dict."""
        code_hash = _hash_code(claim_code)
        email_n = _norm_email(email)
        if not claim_code or not email_n:
            return {"ok": False, "status_code": 400,
                    "error": "Claim code and email are required"}

        with self._lock:
            record = self._by_hash.get(code_hash)
            # Constant-time compare guards against timing oracles on the hash.
            if not record or not hmac.compare_digest(record["code_hash"], code_hash):
                return {"ok": False, "status_code": 404,
                        "error": "That claim code is not valid"}
            if record["status"] != "active":
                return {"ok": False, "status_code": 409,
                        "error": "That claim code has already been used"}
            if not hmac.compare_digest(record["email"], email_n):
                record["attempts"] = int(record.get("attempts") or 0) + 1
                return {"ok": False, "status_code": 403,
                        "error": "Claim code does not match that email address"}
            try:
                if _now() > datetime.fromisoformat(record["expires_at"]):
                    record["status"] = "expired"
                    return {"ok": False, "status_code": 410,
                            "error": "That claim code has expired"}
            except ValueError:
                pass
            return {"ok": True, "record": record}

    def lookup(self, *, claim_code: str, email: str,
               email_has_login: bool) -> Dict[str, Any]:
        """Validate a claim code and report which path the applicant needs.

        ``email_has_login`` is supplied by the caller (the HTTP layer owns the
        user store) so this service stays free of portal state.
        """
        resolved = self._resolve(claim_code, email)
        if not resolved.get("ok"):
            return resolved
        record = resolved["record"]
        return {
            "ok": True,
            "status": STATUS_NEEDS_LOGIN if email_has_login else STATUS_NEEDS_PASSWORD,
            "application_id": record["application_id"],
            "customer_id": record["customer_id"],
            "email": record["email"],
            "policy_id": record["policy_id"],
            "underwriting_id": record["underwriting_id"],
            "customer_name": record["customer_name"],
            "phone": record["phone"],
            "summary": dict(record.get("summary") or {}),
            "expires_at": record["expires_at"],
        }

    # ------------------------------------------------------------------
    # redeem
    # ------------------------------------------------------------------

    def redeem(self, *, claim_code: str, email: str,
               email_has_login: bool) -> Dict[str, Any]:
        """Spend a claim code for account activation.

        Refuses when the email already has a login: a claim code must never be
        able to overwrite an existing account's password.
        """
        with self._lock:
            resolved = self._resolve(claim_code, email)
            if not resolved.get("ok"):
                return resolved
            record = resolved["record"]
            if email_has_login:
                return {
                    "ok": False,
                    "status_code": 409,
                    "status": STATUS_NEEDS_LOGIN,
                    "error": (
                        "An account already exists for this email. "
                        "Please sign in (or reset your password) to track this application."
                    ),
                }
            record["status"] = "used"
            record["used_at"] = _now().isoformat()
            return {
                "ok": True,
                "application_id": record["application_id"],
                "customer_id": record["customer_id"],
                "email": record["email"],
                "policy_id": record["policy_id"],
                "underwriting_id": record["underwriting_id"],
                "customer_name": record["customer_name"],
                "phone": record["phone"],
                "summary": dict(record.get("summary") or {}),
            }

    def restore(self, claim_code: str) -> None:
        """Un-spend a code when downstream account creation failed."""
        code_hash = _hash_code(claim_code)
        with self._lock:
            record = self._by_hash.get(code_hash)
            if record and record["status"] == "used":
                record["status"] = "active"
                record["used_at"] = None

    # ------------------------------------------------------------------
    # introspection (tests / ops)
    # ------------------------------------------------------------------

    def stats(self) -> Dict[str, int]:
        with self._lock:
            counts: Dict[str, int] = {}
            for record in self._by_hash.values():
                counts[record["status"]] = counts.get(record["status"], 0) + 1
            counts["total"] = len(self._by_hash)
            return counts

    def reset(self) -> None:
        with self._lock:
            self._by_hash.clear()
            self._by_application.clear()


_service: Optional[ApplicationClaimService] = None
_service_lock = threading.Lock()


def get_application_claim_service() -> ApplicationClaimService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = ApplicationClaimService()
    return _service


def reset_application_claim_service() -> None:
    """Reset the singleton (tests)."""
    global _service
    with _service_lock:
        _service = None
