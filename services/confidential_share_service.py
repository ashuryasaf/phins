"""Confidential document share-link service.

Admins mint single-use or multi-use share links that unlock HTML viewing of
confidential pages (pitch dashboard, /internal/, /legal/) after the recipient
enters a simple open password. Downloadable artefacts (PDF/MD/DOCX/…) are
intentionally excluded: share cookies never authorise those paths.

Persistence is a locked JSON file under ``database/`` so use counts survive
restarts and concurrent unlocks remain atomic.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "ConfidentialShareService",
    "ShareError",
    "get_confidential_share_service",
    "reset_confidential_share_service_for_tests",
]

_DOWNLOAD_SUFFIXES = (
    ".pdf",
    ".md",
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".csv",
    ".zip",
    ".pptx",
    ".ppt",
)
_DEFAULT_DATA_FILE = "confidential_shares.json"
_PBKDF2_ITERATIONS = 120_000


class ShareError(ValueError):
    """Raised for invalid share operations (safe to surface as API errors)."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ShareError(f"Invalid expires_at: {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def hash_share_password(password: str, salt: Optional[str] = None) -> Dict[str, str]:
    """Hash a share open-password with PBKDF2-SHA256."""
    if not password or len(str(password)) < 4:
        raise ShareError("Share password must be at least 4 characters.")
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password).encode("utf-8"),
        salt.encode("utf-8"),
        _PBKDF2_ITERATIONS,
    ).hex()
    return {"password_hash": digest, "password_salt": salt}


def verify_share_password(password: str, stored_hash: str, salt: str) -> bool:
    if not password or not stored_hash or not salt:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password).encode("utf-8"),
        str(salt).encode("utf-8"),
        _PBKDF2_ITERATIONS,
    ).hex()
    return hmac.compare_digest(digest, str(stored_hash))


def is_downloadable_path(path: str) -> bool:
    """True for binary/export documents that share links must never unlock."""
    normalized = str(path or "").split("?", 1)[0].split("#", 1)[0].lower()
    return any(normalized.endswith(suffix) for suffix in _DOWNLOAD_SUFFIXES)


def normalize_share_path(path: str) -> str:
    """Normalize and validate a share target path (HTML view only)."""
    raw = str(path or "").strip()
    if not raw:
        raise ShareError("path is required.")
    base = raw.split("?", 1)[0].split("#", 1)[0]
    if not base.startswith("/"):
        base = "/" + base
    # Block traversal / absolute schemes.
    if ".." in base or "\\" in base or "://" in base:
        raise ShareError("Invalid share path.")
    lowered = base.lower()
    if is_downloadable_path(lowered):
        raise ShareError(
            "Downloaded documents cannot be shared via share links. "
            "Share an HTML page instead; downloads keep a separate open password."
        )
    if lowered.startswith("/api/"):
        raise ShareError("API endpoints cannot be shared via share links.")
    # Prefer HTML pages; allow bare confidential prefixes only as explicit files.
    if not (lowered.endswith(".html") or lowered.endswith(".htm")):
        raise ShareError("Share links may only target HTML pages.")
    return lowered


class ConfidentialShareService:
    """Thread-safe, file-backed store for confidential share links."""

    def __init__(self, data_path: Optional[str] = None):
        root = Path(__file__).resolve().parent.parent / "database"
        self._path = Path(data_path) if data_path else root / _DEFAULT_DATA_FILE
        self._lock = threading.RLock()
        self._shares: Dict[str, Dict[str, Any]] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        with self._lock:
            if not self._path.exists():
                self._shares = {}
                return
            try:
                payload = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._shares = {}
                return
            shares = payload.get("shares") if isinstance(payload, dict) else None
            if not isinstance(shares, dict):
                self._shares = {}
                return
            self._shares = {
                str(share_id): dict(record)
                for share_id, record in shares.items()
                if isinstance(record, dict)
            }

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        payload = {
            "version": 1,
            "saved_at": _utc_now_iso(),
            "shares": self._shares,
        }
        data = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        # Exclusive create+replace for integrity under concurrent writers.
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(str(tmp), str(self._path))
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_share(
        self,
        *,
        path: str,
        password: str,
        max_uses: Optional[int] = 1,
        expires_at: Optional[str] = None,
        label: str = "",
        created_by: str = "admin",
    ) -> Dict[str, Any]:
        """Create a single-use (max_uses=1) or multi-use share link."""
        target = normalize_share_path(path)
        if max_uses is not None:
            try:
                max_uses_int = int(max_uses)
            except (TypeError, ValueError) as exc:
                raise ShareError("max_uses must be a positive integer or null.") from exc
            if max_uses_int < 1:
                raise ShareError("max_uses must be at least 1 (or null for unlimited).")
        else:
            max_uses_int = None

        expiry = _parse_iso(expires_at)
        if expiry is not None and expiry <= _utc_now():
            raise ShareError("expires_at must be in the future.")

        pwd = hash_share_password(password)
        share_id = "shr_" + secrets.token_urlsafe(18).replace("-", "").replace("_", "")[:24]
        record = {
            "id": share_id,
            "path": target,
            "label": str(label or "").strip()[:120],
            "password_hash": pwd["password_hash"],
            "password_salt": pwd["password_salt"],
            "max_uses": max_uses_int,
            "used_count": 0,
            "expires_at": expiry.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            if expiry
            else None,
            "created_at": _utc_now_iso(),
            "created_by": str(created_by or "admin")[:80],
            "status": "active",
            "use_log": [],
        }
        with self._lock:
            self._shares[share_id] = record
            self._persist()
            return self._public_view(record)

    def list_shares(self, *, include_revoked: bool = True) -> List[Dict[str, Any]]:
        with self._lock:
            items = [self._public_view(self._refresh_status(dict(r))) for r in self._shares.values()]
        if not include_revoked:
            items = [item for item in items if item.get("status") == "active"]
        items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return items

    def get_share(self, share_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            record = self._shares.get(str(share_id or "").strip())
            if not record:
                return None
            return self._public_view(self._refresh_status(dict(record)))

    def get_share_raw(self, share_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            record = self._shares.get(str(share_id or "").strip())
            return dict(record) if record else None

    def revoke_share(self, share_id: str, *, revoked_by: str = "admin") -> Dict[str, Any]:
        with self._lock:
            record = self._shares.get(str(share_id or "").strip())
            if not record:
                raise ShareError("Share link not found.")
            record["status"] = "revoked"
            record["revoked_at"] = _utc_now_iso()
            record["revoked_by"] = str(revoked_by or "admin")[:80]
            self._persist()
            return self._public_view(record)

    def unlock(
        self,
        share_id: str,
        password: str,
        *,
        client_ip: str = "",
        requested_path: str = "",
    ) -> Tuple[Dict[str, Any], str]:
        """Validate password and consume one use. Returns (public_share, path)."""
        sid = str(share_id or "").strip()
        if not sid:
            raise ShareError("share_id is required.")
        with self._lock:
            record = self._shares.get(sid)
            if not record:
                # Same message as a bad password — avoid share-id oracle.
                raise ShareError("Invalid share password.")
            record = self._refresh_status(record)

            if not verify_share_password(
                password,
                str(record.get("password_hash") or ""),
                str(record.get("password_salt") or ""),
            ):
                raise ShareError("Invalid share password.")

            # Password is correct — only now reveal status / remaining-use issues.
            if record.get("status") == "revoked":
                raise ShareError("Share link has been revoked.")
            if record.get("status") == "expired":
                raise ShareError("Share link has expired.")

            target = str(record.get("path") or "")
            if requested_path:
                req = str(requested_path).split("?", 1)[0].split("#", 1)[0].lower()
                if req and req != target:
                    raise ShareError("Share link is not valid for this document.")

            if is_downloadable_path(target):
                # Defence in depth: never unlock a downloadable even if stored.
                raise ShareError("Share links cannot unlock downloaded documents.")

            max_uses = record.get("max_uses")
            used = int(record.get("used_count") or 0)
            if max_uses is not None and used >= int(max_uses):
                record["status"] = "exhausted"
                self._persist()
                raise ShareError("Share link has no remaining uses.")

            record["used_count"] = used + 1
            log = list(record.get("use_log") or [])
            log.append(
                {
                    "at": _utc_now_iso(),
                    "ip": str(client_ip or "")[:64],
                }
            )
            # Cap audit trail size; keep integrity of counts above the log.
            record["use_log"] = log[-50:]
            if max_uses is not None and record["used_count"] >= int(max_uses):
                record["status"] = "exhausted"
            else:
                record["status"] = "active"
            self._shares[sid] = record
            self._persist()
            return self._public_view(record), target

    def share_is_active_for_path(self, share_id: str, path: str) -> bool:
        """True when an existing (already unlocked) share still covers ``path``."""
        with self._lock:
            record = self._shares.get(str(share_id or "").strip())
            if not record:
                return False
            record = self._refresh_status(dict(record), persist=False)
            # Exhausted shares still honour cookies issued at unlock time, but
            # revoked/expired ones must not.
            if record.get("status") == "revoked":
                return False
            expiry = _parse_iso(record.get("expires_at"))
            if expiry is not None and expiry <= _utc_now():
                return False
            target = str(record.get("path") or "")
            req = str(path or "").split("?", 1)[0].split("#", 1)[0].lower()
            if not target or req != target:
                return False
            if is_downloadable_path(req):
                return False
            return True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _refresh_status(
        self, record: Dict[str, Any], *, persist: bool = True
    ) -> Dict[str, Any]:
        status = str(record.get("status") or "active")
        if status == "revoked":
            return record
        expiry = None
        try:
            expiry = _parse_iso(record.get("expires_at"))
        except ShareError:
            expiry = None
        if expiry is not None and expiry <= _utc_now():
            record["status"] = "expired"
            if persist and record.get("id") in self._shares:
                self._shares[record["id"]] = record
                self._persist()
            return record
        max_uses = record.get("max_uses")
        used = int(record.get("used_count") or 0)
        if max_uses is not None and used >= int(max_uses):
            record["status"] = "exhausted"
            if persist and record.get("id") in self._shares:
                self._shares[record["id"]] = record
                self._persist()
            return record
        if status != "active":
            # Do not resurrect revoked/expired.
            return record
        record["status"] = "active"
        return record

    @staticmethod
    def _public_view(record: Dict[str, Any]) -> Dict[str, Any]:
        max_uses = record.get("max_uses")
        used = int(record.get("used_count") or 0)
        remaining = None if max_uses is None else max(0, int(max_uses) - used)
        return {
            "id": record.get("id"),
            "path": record.get("path"),
            "label": record.get("label") or "",
            "max_uses": max_uses,
            "used_count": used,
            "remaining_uses": remaining,
            "mode": "single" if max_uses == 1 else ("multi" if max_uses else "unlimited"),
            "expires_at": record.get("expires_at"),
            "created_at": record.get("created_at"),
            "created_by": record.get("created_by"),
            "status": record.get("status"),
            "revoked_at": record.get("revoked_at"),
            "share_url_path": f"{record.get('path')}?share={record.get('id')}",
        }


_service: Optional[ConfidentialShareService] = None
_service_lock = threading.Lock()


def get_confidential_share_service(
    data_path: Optional[str] = None,
) -> ConfidentialShareService:
    global _service
    with _service_lock:
        if _service is None or data_path is not None:
            _service = ConfidentialShareService(data_path=data_path)
        return _service


def reset_confidential_share_service_for_tests() -> None:
    """Drop the singleton so tests can inject a temp data path."""
    global _service
    with _service_lock:
        _service = None
