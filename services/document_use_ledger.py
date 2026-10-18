"""Append-only ledger of documents sent, signed, opened, and used.

Each entry carries ``prev_hash`` and ``entry_hash``. A row that does not
extend the chain is reported and blocks the next append — nothing is
rewritten to hide the break. The same idempotency key is one event.

The file is the chain. When the database is on, each entry is also sealed
with the signed-document checksum rule so a deploy without this file still
has the events.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple

__all__ = [
    "ACTIONS",
    "LedgerError",
    "DocumentUseLedger",
    "get_document_use_ledger",
    "reset_document_use_ledger_for_tests",
]

ACTIONS = ("sent", "signed", "opened", "used")
_GENESIS = "phins-document-use-ledger-v1"
_ENV_PATH = "PHINS_DOCUMENT_USE_LEDGER_PATH"


class LedgerError(ValueError):
    """The use ledger could not be extended or no longer matches its chain."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _entry_hash(prev_hash: str, body: Mapping[str, Any]) -> str:
    return _sha256(f"{prev_hash}\n{_canonical(body)}")


class DocumentUseLedger:
    def __init__(self, data_path: Optional[str] = None):
        if data_path:
            self._path = Path(data_path)
        else:
            env = os.environ.get(_ENV_PATH, "").strip()
            if env:
                self._path = Path(env)
            else:
                self._path = Path(__file__).resolve().parent.parent / "database" / "document_use_ledger.json"
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    @contextmanager
    def _exclusive_store(self) -> Iterator[None]:
        """In-process lock, then a cross-process ``flock`` on the sibling file.

        Several app workers load-append-replace the same JSON file. Without
        this two workers chain from the same tail and the later ``os.replace``
        drops the other event. The lock lives on its own file because the
        ledger itself is replaced (a new inode) on every write.
        """
        with self._lock:
            try:
                import fcntl  # type: ignore
            except ImportError:  # pragma: no cover - non-POSIX
                yield
                return
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._lock_path, "a+", encoding="utf-8") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def record(self, **fields: Any) -> Dict[str, Any]:
        """Append one event, or return the existing row for its idempotency key."""
        action = str(fields.get("action") or "").strip().lower()
        if action not in ACTIONS:
            raise LedgerError("action must be sent, signed, opened, or used.")
        key = str(fields.get("idempotency_key") or "").strip()
        if not key or len(key) > 180:
            raise LedgerError("idempotency_key is required.")
        body = {
            "action": action,
            "at": str(fields.get("at") or _utc_now_iso())[:40],
            "idempotency_key": key,
            "document_path": str(fields.get("document_path") or "")[:200],
            "document_name": str(fields.get("document_name") or "")[:120],
            "doc_instance_id": str(fields.get("doc_instance_id") or "")[:120],
            "archive_id": str(fields.get("archive_id") or "")[:64],
            "share_id": str(fields.get("share_id") or "")[:80],
            "actor": str(fields.get("actor") or "")[:120],
            "content_sha256": str(fields.get("content_sha256") or "").strip().lower()[:64],
            "entry_id": str(fields.get("entry_id") or "")[:160],
        }
        with self._exclusive_store():
            entries, intact = self._load()
            if not intact:
                raise LedgerError("Document use ledger chain does not verify.")
            for existing in entries:
                if existing.get("idempotency_key") == key:
                    return dict(existing)
            prev = entries[-1]["entry_hash"] if entries else _GENESIS
            row = dict(body)
            row["prev_hash"] = prev
            row["entry_hash"] = _entry_hash(prev, body)
            entries.append(row)
            self._write(entries)
            self._seal_entry(row)
            return dict(row)

    def list_events(self, limit: int = 200) -> Dict[str, Any]:
        """Newest events, plus whether the whole chain still verifies."""
        with self._exclusive_store():
            entries, intact = self._load()
        cap = max(1, min(int(limit or 200), 500))
        view = list(reversed(entries[-cap:]))
        public = []
        for entry in view:
            public.append({key: entry.get(key) for key in (
                "action", "at", "document_path", "document_name", "doc_instance_id",
                "archive_id", "share_id", "actor", "content_sha256", "entry_id",
                "entry_hash", "prev_hash",
            )})
        return {
            "items": public,
            "page": 1,
            "page_size": cap,
            "total": len(entries),
            "intact": intact,
        }

    def _load(self):
        if not self._path.is_file():
            restored, complete = self._restore_from_durable()
            if not complete:
                return restored, False
            if not restored:
                return [], True
            self._write(restored)
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return [], False
        entries = raw.get("entries") if isinstance(raw, dict) else None
        if not isinstance(entries, list):
            return [], False
        prev = _GENESIS
        for entry in entries:
            if not isinstance(entry, dict):
                return entries, False
            body = {key: entry.get(key) for key in (
                "action", "at", "idempotency_key", "document_path", "document_name",
                "doc_instance_id", "archive_id", "share_id", "actor", "content_sha256",
                "entry_id",
            )}
            if entry.get("prev_hash") != prev or entry.get("entry_hash") != _entry_hash(prev, body):
                return entries, False
            if not self._durable_entry_matches(entry):
                return entries, False
            prev = entry["entry_hash"]
        return entries, True

    def _restore_from_durable(self) -> Tuple[List[Dict[str, Any]], bool]:
        """Rebuild the chain from the sealed rows when the file is gone.

        Returns the entries and whether every sealed row was linked into one
        chain from genesis. An unreadable or unlinked row is reported as a
        break so the next append is blocked instead of forking the ledger.
        """
        try:
            from services.signed_document_store import database_enabled, list_asset_ids, load
        except Exception:
            return [], True
        if not database_enabled():
            return [], True
        try:
            asset_ids = list_asset_ids("use_ledger")
        except Exception:
            return [], False
        by_prev: Dict[str, Dict[str, Any]] = {}
        for asset_id in asset_ids:
            if not str(asset_id or "").startswith("dule:"):
                continue
            try:
                payload = load(asset_id)
                entry = json.loads(payload.decode("utf-8")) if payload else None
            except Exception:
                return [], False
            if not isinstance(entry, dict):
                return [], False
            by_prev[str(entry.get("prev_hash") or "")] = entry
        if not by_prev:
            return [], True
        entries: List[Dict[str, Any]] = []
        prev = _GENESIS
        while prev in by_prev:
            entry = by_prev.pop(prev)
            entries.append(entry)
            prev = str(entry.get("entry_hash") or "")
        return entries, not by_prev

    def _write(self, entries: List[Dict[str, Any]]) -> None:
        payload = {"genesis": _GENESIS, "entries": entries}
        raw = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(str(tmp), str(self._path))
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def _seal_entry(self, row: Mapping[str, Any]) -> None:
        """Seal the entry bytes. A failure rolls the file chain back."""
        try:
            from services.signed_document_store import database_enabled, seal
        except Exception:
            return
        if not database_enabled():
            return
        payload = (_canonical(row) + "\n").encode("utf-8")
        asset_id = "dule:" + str(row.get("entry_hash") or "")
        try:
            seal(asset_id, payload, "use_ledger")
        except Exception as exc:
            self._rollback_last(str(row.get("entry_hash") or ""))
            raise LedgerError("Document use ledger could not be sealed.") from exc

    def _rollback_last(self, entry_hash: str) -> None:
        entries, intact = self._load_file_only()
        if not intact or not entries:
            return
        if entries[-1].get("entry_hash") != entry_hash:
            return
        self._write(entries[:-1])

    def _load_file_only(self):
        """File chain only, used when a durable seal fails after the append."""
        if not self._path.is_file():
            return [], True
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return [], False
        entries = raw.get("entries") if isinstance(raw, dict) else None
        if not isinstance(entries, list):
            return [], False
        prev = _GENESIS
        for entry in entries:
            if not isinstance(entry, dict):
                return entries, False
            body = {key: entry.get(key) for key in (
                "action", "at", "idempotency_key", "document_path", "document_name",
                "doc_instance_id", "archive_id", "share_id", "actor", "content_sha256",
                "entry_id",
            )}
            if entry.get("prev_hash") != prev or entry.get("entry_hash") != _entry_hash(prev, body):
                return entries, False
            prev = entry["entry_hash"]
        return entries, True

    @staticmethod
    def _durable_entry_matches(entry: Mapping[str, Any]) -> bool:
        try:
            from services.signed_document_store import database_enabled, load
        except Exception:
            return True
        if not database_enabled():
            return True
        asset_id = "dule:" + str(entry.get("entry_hash") or "")
        try:
            payload = load(asset_id)
        except Exception:
            return False
        if payload is None:
            try:
                from services.signed_document_store import seal
                seal(asset_id, (_canonical(entry) + "\n").encode("utf-8"), "use_ledger")
            except Exception:
                return False
            return True
        return payload == (_canonical(entry) + "\n").encode("utf-8")


_ledger: Optional[DocumentUseLedger] = None
_ledger_lock = threading.Lock()


def get_document_use_ledger(data_path: Optional[str] = None) -> DocumentUseLedger:
    global _ledger
    with _ledger_lock:
        if _ledger is None or data_path is not None:
            _ledger = DocumentUseLedger(data_path)
        return _ledger


def reset_document_use_ledger_for_tests() -> None:
    global _ledger
    with _ledger_lock:
        _ledger = None
