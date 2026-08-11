"""Meeting summary-notes service (admin drafting + future reference).

Admins draft summary notes from meetings (investor, partner, regulatory)
pinned to the pitch dashboard's Meeting Diary. Notes are stored server-side
so they can be referred to later:

- **BI** — notes carry structured fields (meeting_ref, meeting_date,
  counterparty, tags, status) so BI layers can query and aggregate them.
- **Regulatory adjustments** — a dedicated ``regulatory_adjustments`` field
  records adjustments required for further regulatory requirements agreed or
  raised in the meeting.
- **AI-affiliated use** — notes are plain structured JSON that AI surfaces
  may read as context. Consistent with the platform guarantee, AI/BI layers
  may *read* notes but never post: this store is an operational admin record
  and does not write to the platform ledger.

Persistence mirrors ``confidential_share_service``: a JSON file under
``database/`` with an exclusive ``fcntl.flock`` on a sibling ``.lock`` file,
reloading from disk before every mutation so edits stay consistent across
multiple app workers (not just threads in one process).
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

__all__ = [
    "MeetingNotesService",
    "MeetingNoteError",
    "SUGGESTED_TAGS",
    "get_meeting_notes_service",
    "reset_meeting_notes_service_for_tests",
]

_DEFAULT_DATA_FILE = "meeting_notes.json"

# Canonical tags the admin UI offers; free-form tags are also accepted
# (normalized) so future products/workstreams can be tagged without a deploy.
SUGGESTED_TAGS = ("bi", "regulatory", "ai")

_VALID_STATUSES = ("draft", "final")
_TAG_RE = re.compile(r"[^a-z0-9_-]+")

_MAX_TAGS = 12
_MAX_TAG_LEN = 32
_MAX_TITLE_LEN = 160
_MAX_REF_LEN = 160
_MAX_DATE_LEN = 40
_MAX_COUNTERPARTY_LEN = 200
_MAX_TEXT_LEN = 20_000


class MeetingNoteError(ValueError):
    """Raised for invalid note operations (safe to surface as API errors)."""


def _utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def normalize_tags(tags: Any) -> List[str]:
    """Normalize a tag list: lowercase tokens, deduped, order-preserving."""
    if tags is None:
        return []
    if isinstance(tags, str):
        tags = tags.split(",")
    if not isinstance(tags, (list, tuple)):
        raise MeetingNoteError("tags must be a list of short labels.")
    out: List[str] = []
    for raw in tags:
        token = _TAG_RE.sub("-", str(raw or "").strip().lower()).strip("-")
        if not token:
            continue
        token = token[:_MAX_TAG_LEN]
        if token not in out:
            out.append(token)
        if len(out) >= _MAX_TAGS:
            break
    return out


def _clean_text(value: Any, *, max_len: int, field: str, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise MeetingNoteError(f"{field} is required.")
    if len(text) > max_len:
        raise MeetingNoteError(f"{field} is too long (max {max_len} characters).")
    return text


def _clean_status(value: Any, *, default: str = "draft") -> str:
    status = str(value or default).strip().lower()
    if status not in _VALID_STATUSES:
        raise MeetingNoteError("status must be 'draft' or 'final'.")
    return status


class MeetingNotesService:
    """Thread- and multi-worker-safe file-backed store for meeting notes."""

    def __init__(self, data_path: Optional[str] = None):
        root = Path(__file__).resolve().parent.parent / "database"
        self._path = Path(data_path) if data_path else root / _DEFAULT_DATA_FILE
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._lock = threading.RLock()
        self._notes: Dict[str, Dict[str, Any]] = {}
        with self._exclusive_store():
            pass  # initial load under the store lock

    # ------------------------------------------------------------------
    # Persistence / locking
    # ------------------------------------------------------------------

    @contextmanager
    def _exclusive_store(self) -> Iterator[None]:
        """Exclusive cross-process lock + reload. Caller may then mutate + persist."""
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._lock_path, "a+", encoding="utf-8") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    self._load_from_disk()
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _load_from_disk(self) -> None:
        if not self._path.exists():
            self._notes = {}
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._notes = {}
            return
        notes = payload.get("notes") if isinstance(payload, dict) else None
        if not isinstance(notes, dict):
            self._notes = {}
            return
        self._notes = {
            str(note_id): dict(record)
            for note_id, record in notes.items()
            if isinstance(record, dict)
        }

    def _persist(self) -> None:
        """Write the in-memory map. Must be called while holding ``_exclusive_store``."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        payload = {
            "version": 1,
            "saved_at": _utc_now_iso(),
            "notes": self._notes,
        }
        data = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
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

    def create_note(
        self,
        *,
        title: str,
        summary: str,
        meeting_ref: str = "",
        meeting_date: str = "",
        counterparty: str = "",
        decisions: str = "",
        action_items: str = "",
        regulatory_adjustments: str = "",
        tags: Any = None,
        status: str = "draft",
        created_by: str = "admin",
    ) -> Dict[str, Any]:
        """Draft (or directly finalize) a meeting summary note."""
        record = {
            "id": "note_" + secrets.token_urlsafe(18).replace("-", "").replace("_", "")[:24],
            "title": _clean_text(title, max_len=_MAX_TITLE_LEN, field="title", required=True),
            "summary": _clean_text(summary, max_len=_MAX_TEXT_LEN, field="summary", required=True),
            "meeting_ref": _clean_text(meeting_ref, max_len=_MAX_REF_LEN, field="meeting_ref"),
            "meeting_date": _clean_text(meeting_date, max_len=_MAX_DATE_LEN, field="meeting_date"),
            "counterparty": _clean_text(
                counterparty, max_len=_MAX_COUNTERPARTY_LEN, field="counterparty"
            ),
            "decisions": _clean_text(decisions, max_len=_MAX_TEXT_LEN, field="decisions"),
            "action_items": _clean_text(action_items, max_len=_MAX_TEXT_LEN, field="action_items"),
            "regulatory_adjustments": _clean_text(
                regulatory_adjustments, max_len=_MAX_TEXT_LEN, field="regulatory_adjustments"
            ),
            "tags": normalize_tags(tags),
            "status": _clean_status(status),
            "revision": 1,
            "archived": False,
            "created_at": _utc_now_iso(),
            "created_by": str(created_by or "admin")[:80],
            "updated_at": None,
            "updated_by": None,
        }
        with self._exclusive_store():
            self._notes[record["id"]] = record
            self._persist()
            return dict(record)

    _UPDATABLE_TEXT_FIELDS = {
        "title": (_MAX_TITLE_LEN, True),
        "summary": (_MAX_TEXT_LEN, True),
        "meeting_ref": (_MAX_REF_LEN, False),
        "meeting_date": (_MAX_DATE_LEN, False),
        "counterparty": (_MAX_COUNTERPARTY_LEN, False),
        "decisions": (_MAX_TEXT_LEN, False),
        "action_items": (_MAX_TEXT_LEN, False),
        "regulatory_adjustments": (_MAX_TEXT_LEN, False),
    }

    def update_note(
        self,
        note_id: str,
        updates: Dict[str, Any],
        *,
        updated_by: str = "admin",
    ) -> Dict[str, Any]:
        """Apply a partial update (draft edits / finalize) and bump the revision."""
        if not isinstance(updates, dict):
            raise MeetingNoteError("updates must be an object.")
        with self._exclusive_store():
            record = self._notes.get(str(note_id or "").strip())
            if not record:
                raise MeetingNoteError("Meeting note not found.")
            if record.get("archived"):
                raise MeetingNoteError("Archived notes cannot be edited.")
            changed = False
            for field, (max_len, required) in self._UPDATABLE_TEXT_FIELDS.items():
                if field in updates:
                    record[field] = _clean_text(
                        updates[field], max_len=max_len, field=field, required=required
                    )
                    changed = True
            if "tags" in updates:
                record["tags"] = normalize_tags(updates["tags"])
                changed = True
            if "status" in updates:
                record["status"] = _clean_status(updates["status"], default=record["status"])
                changed = True
            if not changed:
                raise MeetingNoteError("No editable fields in update.")
            record["revision"] = int(record.get("revision") or 1) + 1
            record["updated_at"] = _utc_now_iso()
            record["updated_by"] = str(updated_by or "admin")[:80]
            self._notes[str(note_id).strip()] = record
            self._persist()
            return dict(record)

    def archive_note(self, note_id: str, *, archived_by: str = "admin") -> Dict[str, Any]:
        """Archive (soft-delete) a note; it stays queryable for audit/BI."""
        with self._exclusive_store():
            record = self._notes.get(str(note_id or "").strip())
            if not record:
                raise MeetingNoteError("Meeting note not found.")
            record["archived"] = True
            record["archived_at"] = _utc_now_iso()
            record["archived_by"] = str(archived_by or "admin")[:80]
            self._persist()
            return dict(record)

    def get_note(self, note_id: str) -> Optional[Dict[str, Any]]:
        with self._exclusive_store():
            record = self._notes.get(str(note_id or "").strip())
            return dict(record) if record else None

    def list_notes(
        self,
        *,
        tag: Optional[str] = None,
        status: Optional[str] = None,
        meeting_ref: Optional[str] = None,
        include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        """Structured note list (newest first) — the BI/AI read surface."""
        tag_filter = normalize_tags([tag])[0] if tag else None
        status_filter = _clean_status(status) if status else None
        ref_filter = str(meeting_ref or "").strip().lower() or None
        with self._exclusive_store():
            items = [dict(record) for record in self._notes.values()]
        if not include_archived:
            items = [item for item in items if not item.get("archived")]
        if tag_filter:
            items = [item for item in items if tag_filter in (item.get("tags") or [])]
        if status_filter:
            items = [item for item in items if item.get("status") == status_filter]
        if ref_filter:
            items = [
                item
                for item in items
                if ref_filter in str(item.get("meeting_ref") or "").lower()
            ]
        items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return items


_service: Optional[MeetingNotesService] = None
_service_lock = threading.Lock()


def get_meeting_notes_service(data_path: Optional[str] = None) -> MeetingNotesService:
    global _service
    with _service_lock:
        if _service is None or data_path is not None:
            _service = MeetingNotesService(data_path=data_path)
        return _service


def reset_meeting_notes_service_for_tests() -> None:
    """Drop the singleton so tests can inject a temp data path."""
    global _service
    with _service_lock:
        _service = None
