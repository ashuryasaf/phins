"""Confidential document share-link service.

Admins mint single-use or multi-use share links that unlock HTML viewing of
confidential pages (pitch dashboard, /internal/, /legal/) after the recipient
enters a simple open password. Downloadable artefacts (PDF/MD/DOCX/…) are
intentionally excluded: share cookies never authorise those paths.

Persistence is a JSON file under ``database/``. Mutations take an exclusive
``fcntl.flock`` on a sibling ``.lock`` file and reload from disk first so
use counts stay correct across multiple app workers (not just threads in one
process).

Conditional-NDA links (the PHINS Unified Business Plan set): a share created
with ``nda_required=True`` is only unlocked once the recipient has signed the
versioned undertaking in ``services/business_plan_nda.py`` with a full name;
the acceptance (signer, NDA version + SHA-256, drawn-signature digest, time,
address) is kept on the record. Every unlock opens a *session* with its own
access window (default and single-use maximum: three hours from the moment it
opens) and idle timeout; ``share_is_active_for_path`` enforces both, so a link
that is opened and then left alone stops working on its own.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import secrets
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

__all__ = [
    "ConfidentialShareService",
    "DEFAULT_ACCESS_WINDOW_SECONDS",
    "DEFAULT_IDLE_TIMEOUT_SECONDS",
    "MAX_ACCESS_WINDOW_SECONDS",
    "MAX_SINGLE_USE_WINDOW_SECONDS",
    "NDA_LINK_VALIDITY_SECONDS",
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

# Per-opening access window: default and single-use ceiling are three hours
# from the moment the link is opened; multi-use links may run up to a day.
DEFAULT_ACCESS_WINDOW_SECONDS = 3 * 60 * 60
MAX_SINGLE_USE_WINDOW_SECONDS = 3 * 60 * 60
MAX_ACCESS_WINDOW_SECONDS = 24 * 60 * 60
MIN_ACCESS_WINDOW_SECONDS = 5 * 60
# An opened view that is not used closes after this long without activity.
DEFAULT_IDLE_TIMEOUT_SECONDS = 30 * 60
MIN_IDLE_TIMEOUT_SECONDS = 5 * 60
# An NDA link that is never opened lapses after a week.
NDA_LINK_VALIDITY_SECONDS = 7 * 24 * 60 * 60
# Activity is persisted at most this often per session (bounded writes).
_TOUCH_INTERVAL_SECONDS = 60
_SIGNATURE_MAX_BYTES = 96 * 1024
_MAX_SESSIONS = 50


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


def _scope_root(path: str) -> str:
    """Scope root of ``path`` (the plan set shares one root; see security)."""
    try:
        from security.confidential_access import share_scope_root
    except Exception:  # pragma: no cover - security package always present
        return str(path or "").split("?", 1)[0].split("#", 1)[0].lower()
    return share_scope_root(path)


def _same_scope(requested: str, target: str) -> bool:
    req = str(requested or "").split("?", 1)[0].split("#", 1)[0].lower()
    tgt = str(target or "").lower()
    if not req or not tgt:
        return False
    return req == tgt or _scope_root(req) == _scope_root(tgt)


def _bounded_int(value: Any, *, name: str, lo: int, hi: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ShareError(f"{name} must be an integer number of seconds.") from exc
    if number < lo or number > hi:
        raise ShareError(f"{name} must be between {lo} and {hi} seconds.")
    return number


def _signature_digest(signature_png: Optional[str]) -> Tuple[str, str]:
    """Return ``(data_url, sha256)`` for an optional drawn signature.

    Accepts a ``data:image/png;base64,...`` URL; anything else or anything
    above the size cap is refused so the share file stays bounded.
    """
    raw = str(signature_png or "").strip()
    if not raw:
        return "", ""
    if not raw.startswith("data:image/png;base64,"):
        raise ShareError("Signature must be a PNG data URL.")
    if len(raw) > _SIGNATURE_MAX_BYTES:
        raise ShareError("Signature image is too large.")
    import base64

    try:
        payload = base64.b64decode(raw.split(",", 1)[1], validate=True)
    except Exception as exc:
        raise ShareError("Signature image is not valid base64.") from exc
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ShareError("Signature image is not a PNG.")
    return raw, hashlib.sha256(payload).hexdigest()


def _session_is_live(session: Dict[str, Any], idle_timeout: int, now: datetime) -> bool:
    """True while an opening is inside its access window and not idle-closed."""
    until = _parse_iso(session.get("access_until"))
    if until is not None and until <= now:
        return False
    last_seen = _parse_iso(session.get("last_seen_at")) or _parse_iso(session.get("opened_at"))
    if idle_timeout and last_seen is not None and (now - last_seen).total_seconds() > idle_timeout:
        return False
    return True


def _cap_records(
    records: List[Dict[str, Any]],
    *,
    protected: Callable[[Dict[str, Any]], bool],
) -> List[Dict[str, Any]]:
    """Bound a stored list at ``_MAX_SESSIONS``, shedding the oldest other rows.

    A ``protected`` row still authorises a live opening (or carries its NDA
    receipt), so it is kept even when that pushes the list past the cap: the
    cap bounds storage, it is not a session LRU.
    """
    if len(records) <= _MAX_SESSIONS:
        return records
    budget = _MAX_SESSIONS - sum(1 for record in records if protected(record))
    kept: List[Dict[str, Any]] = []
    for record in reversed(records):
        if protected(record):
            kept.append(record)
        elif budget > 0:
            budget -= 1
            kept.append(record)
    kept.reverse()
    return kept


class ConfidentialShareService:
    """Thread- and multi-worker-safe file-backed store for confidential shares."""

    def __init__(self, data_path: Optional[str] = None):
        root = Path(__file__).resolve().parent.parent / "database"
        self._path = Path(data_path) if data_path else root / _DEFAULT_DATA_FILE
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._lock = threading.RLock()
        self._shares: Dict[str, Dict[str, Any]] = {}
        with self._exclusive_store():
            pass  # initial load under the store lock

    # ------------------------------------------------------------------
    # Persistence / locking
    # ------------------------------------------------------------------

    @contextmanager
    def _exclusive_store(self) -> Iterator[None]:
        """Exclusive cross-process lock + reload. Caller may then mutate + persist.

        Order: in-process ``RLock`` first, then ``fcntl.flock`` on the sibling
        lock file, then reload from disk so every worker sees the latest
        ``used_count`` before deciding whether a single-use link is exhausted.
        """
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Open/create the lock file separately from the JSON payload so
            # atomic replace of the data file cannot drop the flock.
            with open(self._lock_path, "a+", encoding="utf-8") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    self._load_from_disk()
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _load_from_disk(self) -> None:
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
        """Write the in-memory map. Must be called while holding ``_exclusive_store``."""
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
        nda_required: bool = False,
        access_window_seconds: Optional[int] = None,
        idle_timeout_seconds: Optional[int] = None,
        lang: str = "en",
        composition: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a single-use (max_uses=1) or multi-use share link.

        ``nda_required`` makes the unlock conditional on a signed NDA (the
        label is the party the undertaking is addressed to, so it is required).
        ``access_window_seconds`` is the per-opening window (default three
        hours; a single-use link can never exceed three hours) and
        ``idle_timeout_seconds`` closes an opened view that sits unused.
        """
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

        clean_label = str(label or "").strip()[:120]
        nda_required = bool(nda_required)
        if nda_required and len(clean_label) < 2:
            raise ShareError("An NDA link needs the recipient's name or organisation as its label.")

        window_cap = MAX_SINGLE_USE_WINDOW_SECONDS if max_uses_int == 1 else MAX_ACCESS_WINDOW_SECONDS
        if access_window_seconds in (None, ""):
            window = min(DEFAULT_ACCESS_WINDOW_SECONDS, window_cap)
        else:
            window = _bounded_int(
                access_window_seconds,
                name="access_window_seconds",
                lo=MIN_ACCESS_WINDOW_SECONDS,
                hi=window_cap,
            )
        if idle_timeout_seconds in (None, ""):
            idle = min(DEFAULT_IDLE_TIMEOUT_SECONDS, window)
        else:
            idle = _bounded_int(
                idle_timeout_seconds,
                name="idle_timeout_seconds",
                lo=MIN_IDLE_TIMEOUT_SECONDS,
                hi=window,
            )

        expiry = _parse_iso(expires_at)
        if expiry is not None and expiry <= _utc_now():
            raise ShareError("expires_at must be in the future.")
        if expiry is None and nda_required:
            from datetime import timedelta

            expiry = _utc_now() + timedelta(seconds=NDA_LINK_VALIDITY_SECONDS)

        lang_code = str(lang or "en").strip().lower()[:2] or "en"
        if lang_code not in ("en", "he"):
            lang_code = "en"
        pwd = hash_share_password(password)
        share_id = "shr_" + secrets.token_urlsafe(18).replace("-", "").replace("_", "")[:24]
        nda_version = None
        nda_digest = None
        nda_effective_date = None
        nda_instance = None
        if nda_required:
            # The platform NDA (/legal/nda.html) instantiated for this link:
            # the Receiving Party is the label and the effective date is the
            # day the link is minted, so the digest is fixed at creation and
            # is what every signer on this link attests to.
            from services.business_plan_nda import NDA_VERSION, doc_instance_id, nda_sha256

            nda_version = NDA_VERSION
            nda_effective_date = _utc_now().date().isoformat()
            nda_digest = nda_sha256(lang_code, label=clean_label, effective_date=nda_effective_date)
            nda_instance = doc_instance_id(share_id)

        record = {
            "id": share_id,
            "path": target,
            "label": clean_label,
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
            "lang": lang_code,
            "nda_required": nda_required,
            "nda_version": nda_version,
            "nda_sha256": nda_digest,
            "nda_effective_date": nda_effective_date,
            "nda_doc_instance_id": nda_instance,
            "nda_acceptances": [],
            "access_window_seconds": int(window),
            "idle_timeout_seconds": int(idle),
            "sessions": [],
            # Frozen chapters + adjustable factors for a business-plan link.
            # None on every other document (and on links minted before this).
            "composition": dict(composition) if isinstance(composition, dict) else None,
        }
        with self._exclusive_store():
            self._shares[share_id] = record
            self._persist()
            return self._public_view(record)

    def list_shares(self, *, include_revoked: bool = True) -> List[Dict[str, Any]]:
        with self._exclusive_store():
            dirty = False
            items = []
            for record in self._shares.values():
                before = record.get("status")
                refreshed = self._refresh_status(dict(record))
                if refreshed.get("status") != before:
                    self._shares[str(refreshed.get("id"))] = refreshed
                    dirty = True
                items.append(self._public_view(refreshed))
            if dirty:
                self._persist()
        if not include_revoked:
            items = [item for item in items if item.get("status") == "active"]
        items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return items

    def get_share(self, share_id: str) -> Optional[Dict[str, Any]]:
        with self._exclusive_store():
            record = self._shares.get(str(share_id or "").strip())
            if not record:
                return None
            before = record.get("status")
            refreshed = self._refresh_status(dict(record))
            if refreshed.get("status") != before:
                self._shares[str(share_id).strip()] = refreshed
                self._persist()
            return self._public_view(refreshed)

    def get_share_raw(self, share_id: str) -> Optional[Dict[str, Any]]:
        with self._exclusive_store():
            record = self._shares.get(str(share_id or "").strip())
            return dict(record) if record else None

    def revoke_share(self, share_id: str, *, revoked_by: str = "admin") -> Dict[str, Any]:
        with self._exclusive_store():
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
        signer_name: str = "",
        signature_png: Optional[str] = None,
        nda_accepted: bool = False,
        user_agent: str = "",
    ) -> Tuple[Dict[str, Any], str]:
        """Validate password and consume one use. Returns (public_share, path).

        For an NDA link the caller must also pass ``nda_accepted=True`` and a
        ``signer_name``; the acceptance is recorded before the use is counted.
        The returned view carries ``session_key`` for the opening just created
        (the cookie binds to it so the access window and idle timeout apply).
        """
        sid = str(share_id or "").strip()
        if not sid:
            raise ShareError("share_id is required.")
        clean_signer = " ".join(str(signer_name or "").split())[:120]
        signature_data, signature_sha = _signature_digest(signature_png)
        with self._exclusive_store():
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
                if req and not _same_scope(req, target):
                    raise ShareError("Share link is not valid for this document.")

            if is_downloadable_path(target):
                # Defence in depth: never unlock a downloadable even if stored.
                raise ShareError("Share links cannot unlock downloaded documents.")

            if record.get("nda_required"):
                if not nda_accepted:
                    raise ShareError("The Non-Disclosure Agreement (NDA) must be accepted to open this link.")
                if len(clean_signer) < 2 or not any(ch.isalpha() for ch in clean_signer):
                    raise ShareError("Sign the NDA with your full name to open this link.")

            max_uses = record.get("max_uses")
            used = int(record.get("used_count") or 0)
            if max_uses is not None and used >= int(max_uses):
                record["status"] = "exhausted"
                self._shares[sid] = record
                self._persist()
                raise ShareError("Share link has no remaining uses.")

            now = _utc_now()
            now_iso = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            session_key = secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:16]
            window = int(record.get("access_window_seconds") or DEFAULT_ACCESS_WINDOW_SECONDS)
            from datetime import timedelta

            access_until = (now + timedelta(seconds=window)).replace(microsecond=0)
            acceptance = None
            if record.get("nda_required"):
                acceptance = {
                    "at": now_iso,
                    "session_key": session_key,
                    "signer_name": clean_signer,
                    "nda_version": record.get("nda_version"),
                    "nda_sha256": record.get("nda_sha256"),
                    "nda_effective_date": record.get("nda_effective_date"),
                    "doc_instance_id": record.get("nda_doc_instance_id"),
                    "lang": record.get("lang") or "en",
                    "signature_method": "draw" if signature_data else "type",
                    "signature_sha256": signature_sha or None,
                    "signature_png": signature_data or None,
                    "ip": str(client_ip or "")[:64],
                    "user_agent": str(user_agent or "")[:200],
                    "ledger": None,
                }
                acceptances = list(record.get("nda_acceptances") or [])
                acceptances.append(acceptance)
                record["nda_acceptances"] = acceptances

            record["used_count"] = used + 1
            log = list(record.get("use_log") or [])
            log.append(
                {
                    "at": now_iso,
                    "ip": str(client_ip or "")[:64],
                    "session_key": session_key,
                    "signer_name": clean_signer or None,
                }
            )
            # Cap audit trail size; keep integrity of counts above the log.
            record["use_log"] = log[-50:]
            sessions = list(record.get("sessions") or [])
            sessions.append(
                {
                    "key": session_key,
                    "opened_at": now_iso,
                    "access_until": access_until.isoformat().replace("+00:00", "Z"),
                    "last_seen_at": now_iso,
                    "signer_name": clean_signer or None,
                    "ip": str(client_ip or "")[:64],
                }
            )
            # Bound the stored openings without closing one that is still
            # live: a missing session key is an immediate deny, so a recipient
            # who already signed must not lose the window to a later signer.
            idle_timeout = int(record.get("idle_timeout_seconds") or 0)
            record["sessions"] = _cap_records(
                sessions, protected=lambda s: _session_is_live(s, idle_timeout, now)
            )
            live_keys = {str(s.get("key")) for s in record["sessions"]}
            if record.get("nda_acceptances"):
                record["nda_acceptances"] = _cap_records(
                    list(record["nda_acceptances"]),
                    protected=lambda a: str(a.get("session_key")) in live_keys,
                )
            if max_uses is not None and record["used_count"] >= int(max_uses):
                record["status"] = "exhausted"
            else:
                record["status"] = "active"
            self._shares[sid] = record
            self._persist()
            view = self._public_view(record)
            view["session_key"] = session_key
            view["access_until"] = sessions[-1]["access_until"]
            view["signer_name"] = clean_signer or None
            view["signature_method"] = (acceptance or {}).get("signature_method")
            return view, target

    def rollback_opening(self, share_id: str, session_key: str) -> bool:
        """Undo the opening ``unlock`` just created (its use, session and NDA record).

        Used when the step that must follow an NDA unlock — anchoring the
        signature on the platform ledger — fails: the link must not count a
        use, nor keep an acceptance, that was never anchored.
        """
        key = str(session_key or "").strip()
        with self._exclusive_store():
            record = self._shares.get(str(share_id or "").strip())
            if not record or not key:
                return False
            sessions = [s for s in (record.get("sessions") or []) if s.get("key") != key]
            if len(sessions) == len(record.get("sessions") or []):
                return False
            record["sessions"] = sessions
            record["nda_acceptances"] = [
                a for a in (record.get("nda_acceptances") or []) if a.get("session_key") != key
            ]
            record["use_log"] = [u for u in (record.get("use_log") or []) if u.get("session_key") != key]
            record["used_count"] = max(0, int(record.get("used_count") or 0) - 1)
            if record.get("status") == "exhausted":
                record["status"] = "active"
            self._refresh_status(record)
            self._shares[str(share_id).strip()] = record
            self._persist()
            return True

    def attach_ledger_receipt(
        self, share_id: str, session_key: str, receipt: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Store the platform-ledger anchor of the NDA signature for an opening."""
        key = str(session_key or "").strip()
        clean = {
            "entry_id": str(receipt.get("entry_id") or "")[:160] or None,
            "sequence_no": receipt.get("sequence_no"),
            "entry_hash": str(receipt.get("entry_hash") or "")[:128] or None,
            "doc_instance_id": str(receipt.get("doc_instance_id") or "")[:120] or None,
            "role": str(receipt.get("role") or "")[:80] or None,
            "signed_at": str(receipt.get("signed_at") or "")[:40] or None,
            "archive_id": str(receipt.get("archive_id") or "")[:64] or None,
        }
        with self._exclusive_store():
            record = self._shares.get(str(share_id or "").strip())
            if not record or not key:
                return None
            acceptances = list(record.get("nda_acceptances") or [])
            target = next((a for a in acceptances if a.get("session_key") == key), None)
            if target is None:
                return None
            target["ledger"] = clean
            record["nda_acceptances"] = acceptances
            self._shares[str(share_id).strip()] = record
            self._persist()
            return dict(clean)

    def share_is_active_for_path(
        self, share_id: str, path: str, session_key: str = ""
    ) -> bool:
        """True when an existing (already unlocked) share still covers ``path``.

        With a ``session_key`` (bound into the share cookie at unlock) the
        opening's access window and idle timeout are enforced and the
        activity stamp is refreshed; without one, legacy cookies are honoured
        on the share-level rules only.
        """
        with self._exclusive_store():
            record = self._shares.get(str(share_id or "").strip())
            if not record:
                return False
            record = self._refresh_status(dict(record))
            # Exhausted shares still honour cookies issued at unlock time, but
            # revoked/expired ones must not.
            if record.get("status") == "revoked":
                return False
            expiry = _parse_iso(record.get("expires_at"))
            if expiry is not None and expiry <= _utc_now():
                # An NDA/windowed link that lapses still lets a session that
                # opened in time run to the end of its own window.
                if not session_key:
                    return False
            target = str(record.get("path") or "")
            req = str(path or "").split("?", 1)[0].split("#", 1)[0].lower()
            if not target or not _same_scope(req, target):
                return False
            if is_downloadable_path(req):
                return False
            key = str(session_key or "").strip()
            if not key:
                # An NDA link has no anonymous cookie: every opening is a
                # signed session. Legacy non-NDA cookies (no session key)
                # keep the share-level expiry check only.
                if record.get("nda_required"):
                    return False
                return expiry is None or expiry > _utc_now()
            if record.get("nda_required"):
                accepted = any(
                    a.get("session_key") == key
                    for a in (record.get("nda_acceptances") or [])
                )
                if not accepted:
                    return False
            sessions = list(record.get("sessions") or [])
            session = next((s for s in sessions if s.get("key") == key), None)
            if session is None:
                return False
            now = _utc_now()
            if not _session_is_live(session, int(record.get("idle_timeout_seconds") or 0), now):
                return False
            last_seen = _parse_iso(session.get("last_seen_at")) or _parse_iso(session.get("opened_at"))
            if last_seen is None or (now - last_seen).total_seconds() >= _TOUCH_INTERVAL_SECONDS:
                session["last_seen_at"] = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
                record["sessions"] = sessions
                self._shares[str(share_id).strip()] = record
                self._persist()
            return True

    def viewer_context(self, share_id: str, session_key: str = "") -> Optional[Dict[str, Any]]:
        """What the protected view may show about the opening (no secrets)."""
        with self._exclusive_store():
            record = self._shares.get(str(share_id or "").strip())
            if not record:
                return None
            key = str(session_key or "").strip()
            session = next(
                (s for s in (record.get("sessions") or []) if s.get("key") == key),
                None,
            ) if key else None
            if session is None and record.get("sessions"):
                session = record["sessions"][-1]
            acceptance = next(
                (a for a in (record.get("nda_acceptances") or [])
                 if session and a.get("session_key") == session.get("key")),
                None,
            )
            return {
                "share_id": record.get("id"),
                "label": record.get("label") or "",
                "lang": record.get("lang") or "en",
                "nda_required": bool(record.get("nda_required")),
                "nda_version": record.get("nda_version"),
                "nda_doc_instance_id": record.get("nda_doc_instance_id"),
                "nda_ledger": dict(acceptance.get("ledger") or {}) if acceptance and acceptance.get("ledger") else None,
                "signer_name": (session or {}).get("signer_name"),
                "opened_at": (session or {}).get("opened_at"),
                "access_until": (session or {}).get("access_until"),
                "idle_timeout_seconds": int(record.get("idle_timeout_seconds") or 0),
                "access_window_seconds": int(record.get("access_window_seconds") or 0),
                "mode": "single" if record.get("max_uses") == 1 else ("multi" if record.get("max_uses") else "unlimited"),
                "composition": dict(record.get("composition") or {}) or None,
            }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _refresh_status(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Derive expired/exhausted status in-place. Caller persists under store lock."""
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
            return record
        max_uses = record.get("max_uses")
        used = int(record.get("used_count") or 0)
        if max_uses is not None and used >= int(max_uses):
            record["status"] = "exhausted"
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
            "lang": record.get("lang") or "en",
            "nda_required": bool(record.get("nda_required")),
            "nda_version": record.get("nda_version"),
            "nda_sha256": record.get("nda_sha256"),
            "nda_effective_date": record.get("nda_effective_date"),
            "nda_doc_instance_id": record.get("nda_doc_instance_id"),
            "composition": dict(record.get("composition")) if isinstance(record.get("composition"), dict) else None,
            "access_window_seconds": int(
                record.get("access_window_seconds") or DEFAULT_ACCESS_WINDOW_SECONDS
            ),
            "idle_timeout_seconds": int(record.get("idle_timeout_seconds") or 0),
            "scope": _scope_root(str(record.get("path") or "")),
            "openings": [
                {
                    "opened_at": s.get("opened_at"),
                    "access_until": s.get("access_until"),
                    "last_seen_at": s.get("last_seen_at"),
                    "signer_name": s.get("signer_name"),
                }
                for s in (record.get("sessions") or [])
            ],
            "nda_acceptances": [
                {
                    "at": a.get("at"),
                    "signer_name": a.get("signer_name"),
                    "nda_version": a.get("nda_version"),
                    "nda_sha256": a.get("nda_sha256"),
                    "signature_method": a.get("signature_method") or ("draw" if a.get("signature_png") else "type"),
                    "signature_sha256": a.get("signature_sha256"),
                    "signed_drawing": bool(a.get("signature_png")),
                    "doc_instance_id": a.get("doc_instance_id") or record.get("nda_doc_instance_id"),
                    "ledger": dict(a.get("ledger") or {}) if a.get("ledger") else None,
                }
                for a in (record.get("nda_acceptances") or [])
            ],
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
