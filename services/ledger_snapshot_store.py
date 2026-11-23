"""Database copy of the platform ledger snapshot file.

``web_portal/server.py`` keeps health wallets, wallet withdrawals, the NFT
ledger, investment accounts, the PHINS balance sheet, algo balances, policy
documents and auto-pay reports in one JSON file (``phins_ledger_data.json``).
On Railway that file sits in ``/data``; when no volume is mounted there, it is
gone after every redeploy and those stores restart empty. This store keeps the
same snapshot as one checksummed ``agent_artifacts`` row so the next boot can
restore it when the file is missing.

Rules:

* Stores that are already authoritative in PostgreSQL (platform ledger rows,
  media library, design document, policies, customers, billing, claims) are
  left out of the copy; boot hydrates them from their own tables.
* Only the long-running server writes the row (``enable()``); one-shot
  commands never touch it, so a cron container cannot race the server.
* The row is read before the first write. A checksum mismatch, an unknown
  format or a failed read blocks every write for this process: the row is
  kept as it is and is not overwritten with a fresh (empty) state.
* Writes are throttled (``PHINS_LEDGER_SNAPSHOT_DB_INTERVAL``, default 60 s);
  a throttled snapshot is held and written by the next flush. A forced write
  (shutdown) ignores the throttle. An older snapshot never replaces a newer
  one.
* A snapshot above ``PHINS_LEDGER_SNAPSHOT_DB_MAX_BYTES`` (default 64 MiB) is
  not written and is reported. The copy then no longer follows the live
  state, so a small marker row records that. A later boot does not apply a
  marked copy and does not write over it. The marker names the copy it was
  set against and is removed after the next snapshot that fits; a marker
  left behind by a removal that did not complete names an earlier copy and
  is ignored.
* Every attempt, written or not, starts the throttle window.
"""

from __future__ import annotations

import json
import hashlib
import logging
import os
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

AGENT_ID = 'platform_persistence'
KIND = 'ledger_snapshot'
ARTIFACT_ID = 'platform-ledger-snapshot'
FORMAT = 'phins-ledger-snapshot/1'
STALE_ARTIFACT_ID = 'platform-ledger-snapshot-stale'
STALE_KIND = 'ledger_snapshot_stale'

DB_AUTHORITATIVE_KEYS = (
    'transaction_ledger',
    'media_assets',
    'media_processing_jobs',
    'design_settings',
    'billing',
    'policies',
    'customers',
    'underwriting_applications',
    'claims',
)

DEFAULT_INTERVAL_SECONDS = 60
DEFAULT_MAX_BYTES = 64 * 1024 * 1024


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def build_payload(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """The stored form of a frozen ledger snapshot (DB-authoritative keys dropped)."""
    data = {k: v for k, v in snapshot.items() if k not in DB_AUTHORITATIVE_KEYS}
    return {
        'format': FORMAT,
        'saved_at': snapshot.get('saved_at'),
        'version': snapshot.get('version'),
        'omitted': sorted(k for k in snapshot if k in DB_AUTHORITATIVE_KEYS),
        'data': data,
    }


def _default_db_factory():
    from database.manager import DatabaseManager
    return DatabaseManager()


class LedgerSnapshotStore:
    def __init__(
        self,
        db_factory: Optional[Callable[[], Any]] = None,
        *,
        min_interval_seconds: Optional[int] = None,
        max_bytes: Optional[int] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._db_factory = db_factory or _default_db_factory
        self.min_interval = (
            _env_int('PHINS_LEDGER_SNAPSHOT_DB_INTERVAL', DEFAULT_INTERVAL_SECONDS)
            if min_interval_seconds is None else max(0, int(min_interval_seconds))
        )
        self.max_bytes = (
            _env_int('PHINS_LEDGER_SNAPSHOT_DB_MAX_BYTES', DEFAULT_MAX_BYTES, minimum=1)
            if max_bytes is None else max(1, int(max_bytes))
        )
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self.enabled = False
        self.checked = False
        self.blocked_reason: Optional[str] = None
        self._seq = 0
        self._written_seq = 0
        self._pending: Optional[Tuple[int, Dict[str, Any]]] = None
        self._last_write_at: Optional[float] = None
        self.last_status: Optional[str] = None
        self.last_saved_at: Optional[str] = None
        self.last_sha256: Optional[str] = None
        self.last_bytes = 0
        self._stale_marked = False
        self.stale = False

    def enable(self) -> None:
        self.enabled = True

    # ------------------------------------------------------------------ read
    def load(self) -> Tuple[str, Optional[Dict[str, Any]]]:
        """Read the stored copy: ``ok``, ``missing``, ``mismatch``, ``unsupported``, ``stale``, ``error``.

        Anything other than ``ok`` / ``missing`` blocks later writes.
        """
        if not self.enabled:
            return 'disabled', None
        try:
            with self._db_factory() as db:
                status, payload = db.agent_artifacts.load_checked(ARTIFACT_ID)
                stale_status, stale = db.agent_artifacts.load_checked(STALE_ARTIFACT_ID)
        except Exception as exc:
            return self._block('error', f"read failed: {type(exc).__name__}")
        if status == 'mismatch':
            return self._block('mismatch', 'stored checksum does not match')
        if status == 'missing':
            self.checked = True
            return 'missing', None
        if (not isinstance(payload, dict) or payload.get('format') != FORMAT
                or not isinstance(payload.get('data'), dict)):
            return self._block('unsupported', 'stored row is not a ledger snapshot')
        if stale_status != 'missing' and self._marker_is_leftover(stale, payload):
            # The copy was written again after the marker was set, and the
            # marker's removal did not complete. The copy is current; the
            # marker goes with the next write.
            logger.warning("ledger snapshot stale marker is older than the stored copy; ignored")
            self._stale_marked = True
        elif stale_status != 'missing':
            since = stale.get('since') if isinstance(stale, dict) else None
            result = self._block(
                'stale',
                f"the copy stopped following the live state (since {since or 'unknown'})",
            )
            self.stale = True
            self.last_saved_at = payload.get('saved_at')
            return result
        self.checked = True
        self.last_saved_at = payload.get('saved_at')
        return 'ok', payload['data']

    @staticmethod
    def _marker_is_leftover(marker: Any, copy: Dict[str, Any]) -> bool:
        """True when the marker names an earlier copy than the one stored.

        A marker that cannot be read, or that names no copy, is not leftover:
        the copy stays refused.
        """
        if not isinstance(marker, dict) or not marker.get('last_copy_saved_at'):
            return False
        return marker['last_copy_saved_at'] != copy.get('saved_at')

    def _block(self, status: str, reason: str) -> Tuple[str, None]:
        self.block(reason)
        logger.error("ledger snapshot DB copy blocked (%s): %s", status, reason)
        return status, None

    def supersede_stale(self) -> bool:
        """Lift the block of a copy that stopped updating.

        Only for a caller that has restored a whole snapshot which is not
        older than that copy. The marker row goes with the next write.
        """
        if not self.stale:
            return False
        self.stale = False
        self.blocked_reason = None
        self.last_status = None
        self._stale_marked = True
        return True

    def block(self, reason: str) -> None:
        """Refuse every later write for this process; the stored row is kept."""
        self.checked = True
        self.stale = False
        self.blocked_reason = reason
        self.last_status = 'blocked'

    # ----------------------------------------------------------------- write
    def offer(self, snapshot: Dict[str, Any], *, force: bool = False) -> str:
        """Hold the newest frozen snapshot and write it when the throttle allows."""
        if not self.enabled:
            return 'disabled'
        with self._lock:
            self._seq += 1
            self._pending = (self._seq, snapshot)
        return self.flush(force=force)

    def flush(self, *, force: bool = False) -> str:
        """Write the held snapshot. Returns the outcome of this call."""
        if not self.enabled:
            return 'disabled'
        if not self.checked:
            self.load()
        if self.blocked_reason:
            return 'blocked'
        with self._lock:
            if self._pending is None:
                return 'idle'
            if (not force and self._last_write_at is not None
                    and self._clock() - self._last_write_at < self.min_interval):
                return 'throttled'
        # A forced write waits for a running one; otherwise the next flush
        # picks the held snapshot up.
        if not self._write_lock.acquire(blocking=force):
            return 'busy'
        try:
            with self._lock:
                pending = self._pending
            if pending is None:
                return 'idle'
            seq, snapshot = pending
            if seq <= self._written_seq:
                return 'idle'
            status = self._write(snapshot)
            with self._lock:
                # A snapshot that does not fit will not fit on a retry; a
                # failed write is kept and retried after the window.
                if status in ('written', 'too_large'):
                    self._written_seq = max(self._written_seq, seq)
                    if self._pending is not None and self._pending[0] == seq:
                        self._pending = None
                self._last_write_at = self._clock()
            return status
        finally:
            self._write_lock.release()

    def _write(self, snapshot: Dict[str, Any]) -> str:
        payload = build_payload(snapshot)
        text = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        size = len(text.encode('utf-8'))
        if size > self.max_bytes:
            self.last_status = 'too_large'
            self.last_bytes = size
            logger.error("ledger snapshot DB copy skipped: %d bytes exceeds cap %d",
                         size, self.max_bytes)
            self._mark_stale(payload.get('saved_at'))
            return 'too_large'
        # The repository serialises with default=str too; round-trip so the
        # stored text and the digest below describe the same document.
        stored = json.loads(text)
        try:
            with self._db_factory() as db:
                db.agent_artifacts.upsert(
                    ARTIFACT_ID, agent_id=AGENT_ID, kind=KIND, payload=stored,
                    subject_type='platform', subject_id='ledger',
                )
        except Exception as exc:
            self.last_status = 'error'
            logger.error("ledger snapshot DB copy write failed: %s", type(exc).__name__)
            return 'error'
        self.last_status = 'written'
        self.last_saved_at = payload.get('saved_at')
        self.last_sha256 = hashlib.sha256(text.encode('utf-8')).hexdigest()
        self.last_bytes = size
        self._clear_stale()
        return 'written'

    def _mark_stale(self, since: Any) -> None:
        """Record durably that the stored copy no longer follows the live state."""
        if self._stale_marked:
            return
        try:
            with self._db_factory() as db:
                status, copy = db.agent_artifacts.load_checked(ARTIFACT_ID)
                if status == 'missing':
                    return  # nothing stored, so nothing a later boot could restore
                copy_saved_at = copy.get('saved_at') if isinstance(copy, dict) else None
                db.agent_artifacts.upsert(
                    STALE_ARTIFACT_ID, agent_id=AGENT_ID, kind=STALE_KIND,
                    payload={'reason': 'too_large', 'since': since,
                             'last_copy_saved_at': copy_saved_at},
                    subject_type='platform', subject_id='ledger',
                )
            self._stale_marked = True
        except Exception as exc:
            logger.error("ledger snapshot stale marker not written: %s", type(exc).__name__)

    def _clear_stale(self) -> None:
        if not self._stale_marked:
            return
        try:
            with self._db_factory() as db:
                db.agent_artifacts.delete_artifact(STALE_ARTIFACT_ID)
            self._stale_marked = False
        except Exception as exc:
            logger.error("ledger snapshot stale marker not cleared: %s", type(exc).__name__)

    # ---------------------------------------------------------------- report
    def status(self) -> Dict[str, Any]:
        with self._lock:
            pending = self._pending is not None and self._pending[0] > self._written_seq
        if not self.enabled:
            state = 'disabled'
        elif self.blocked_reason:
            state = 'blocked'
        elif self.last_status in ('error', 'too_large'):
            state = self.last_status
        elif pending:
            state = 'pending'
        elif self.last_status == 'written' or self.last_saved_at:
            state = 'ok'
        else:
            state = 'empty'
        return {
            'state': state,
            'saved_at': self.last_saved_at,
            'blocked_reason': self.blocked_reason,
        }
