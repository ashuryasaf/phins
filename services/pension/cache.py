"""Content-addressed cache of *parsed* Mislaka data (B5).

Parsing a Mislaka XML/ZIP is the expensive, deterministic part of the pension
pipeline; enrichment and the report text are cheap and depend on the clock
(report date, age), so only the parser output is cached:

* ``xml`` — ``_parse_mislaka_xml`` result for one XML document
* ``zip`` — the aggregated ``ClientProfile.to_dict()`` for a whole archive

Keys are ``sha256(bytes)`` plus ``PARSER_VERSION``; a parser change therefore
never serves stale output. Two tiers: a bounded process-local LRU, and — in
DB mode — rows in ``agent_artifacts`` (``agent_id='pension_data_agent'``,
``kind='parse_result'``) so peers and restarts reuse the work. Rows are
checksum-verified by the repository on read; a corrupted row is skipped, never
served. Values are deep-copied on both sides so a caller mutating its copy
(Risk Reports normalises the client block in place) cannot poison the cache.

The cached payload contains whatever the source file contained — including the
client's national ID — exactly like the parsed documents Risk Reports already
persists in the same table; nothing new leaves the platform.
"""

import copy
import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger('services.pension_data_agent')

PARSER_VERSION = '3'
AGENT_ID = 'pension_data_agent'
KIND = 'parse_result'

ENABLED_ENV = 'PHINS_PENSION_PARSE_CACHE'
MAX_ENV = 'PHINS_PENSION_PARSE_CACHE_MAX'
DEFAULT_MAX = 128
DURABLE_RETRY_SECONDS = 60.0


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == '':
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _db_mode() -> bool:
    try:
        from services.hydrated_store import db_mode_enabled
        return db_mode_enabled()
    except Exception:
        return False


def _db_manager():
    from database.manager import DatabaseManager
    return DatabaseManager()


class ParseResultCache:
    """Bounded LRU in front of ``agent_artifacts`` for parser output."""

    def __init__(self, max_entries: Optional[int] = None,
                 enabled: Optional[bool] = None, db_factory=None):
        self.max_entries = max_entries or _env_int(MAX_ENV, DEFAULT_MAX)
        self._enabled = _env_flag(ENABLED_ENV, True) if enabled is None else bool(enabled)
        self._db_factory = db_factory or _db_manager
        self._lock = threading.Lock()
        self._data: 'OrderedDict[str, Dict[str, Any]]' = OrderedDict()
        # After a table error the durable tier is skipped for a while so a
        # broken database cannot slow every parse down; the LRU keeps working.
        self._durable_down_until = 0.0
        self.stats = {'hits': 0, 'misses': 0, 'durable_hits': 0, 'puts': 0, 'errors': 0}

    def _durable_available(self) -> bool:
        return _db_mode() and time.monotonic() >= self._durable_down_until

    def _durable_failed(self, what: str, exc: Exception) -> None:
        self.stats['errors'] += 1
        self._durable_down_until = time.monotonic() + DURABLE_RETRY_SECONDS
        logger.warning("pension parse cache %s failed (durable tier paused %ds): %s",
                       what, int(DURABLE_RETRY_SECONDS), exc)

    # -- keys -----------------------------------------------------------------
    @staticmethod
    def key(source_kind: str, sha256: str) -> str:
        return f"PENSION-{source_kind}-{sha256}-v{PARSER_VERSION}"

    @property
    def enabled(self) -> bool:
        return self._enabled

    # -- read -----------------------------------------------------------------
    def get(self, source_kind: str, sha256: str) -> Optional[Any]:
        """Parsed data for ``sha256`` or ``None``. Always a private deep copy."""
        if not self._enabled:
            return None
        key = self.key(source_kind, sha256)
        with self._lock:
            record = self._data.get(key)
            if record is not None:
                self._data.move_to_end(key)
                self.stats['hits'] += 1
                return copy.deepcopy(record['data'])
        record = self._durable_get(key)
        if record is None:
            with self._lock:
                self.stats['misses'] += 1
            return None
        with self._lock:
            self._remember(key, record)
            self.stats['hits'] += 1
            self.stats['durable_hits'] += 1
        return copy.deepcopy(record['data'])

    def _durable_get(self, key: str) -> Optional[Dict[str, Any]]:
        if not self._durable_available():
            return None
        try:
            with self._db_factory() as db:
                payload = db.agent_artifacts.get_payload(key)
        except Exception as exc:
            self._durable_failed('read', exc)
            return None
        if not isinstance(payload, dict) or payload.get('parser_version') != PARSER_VERSION \
                or 'data' not in payload:
            return None
        return payload

    # -- write ----------------------------------------------------------------
    def put(self, source_kind: str, sha256: str, data: Any) -> None:
        if not self._enabled:
            return
        key = self.key(source_kind, sha256)
        record = {
            'source_kind': source_kind,
            'sha256': sha256,
            'parser_version': PARSER_VERSION,
            'cached_at': datetime.now(timezone.utc).isoformat(),
            'data': copy.deepcopy(data),
        }
        with self._lock:
            self._remember(key, record)
            self.stats['puts'] += 1
        self._durable_put(key, record)

    def _remember(self, key: str, record: Dict[str, Any]) -> None:
        self._data[key] = record
        self._data.move_to_end(key)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)

    def _durable_put(self, key: str, record: Dict[str, Any]) -> None:
        if not self._durable_available():
            return
        try:
            with self._db_factory() as db:
                db.agent_artifacts.upsert(
                    key, agent_id=AGENT_ID, kind=KIND, payload=record,
                    subject_type='pension_source', subject_id=record['sha256'][:32])
                db.agent_artifacts.prune(AGENT_ID, KIND, self.max_entries)
        except Exception as exc:
            self._durable_failed('write', exc)

    # -- maintenance ----------------------------------------------------------
    def clear(self) -> None:
        """Drop the process-local tier (durable rows are left alone)."""
        with self._lock:
            self._data.clear()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                'enabled': self._enabled,
                'parser_version': PARSER_VERSION,
                'max_entries': self.max_entries,
                'cached': len(self._data),
                'durable': _db_mode(),
                'durable_paused': _db_mode() and time.monotonic() < self._durable_down_until,
                **self.stats,
            }


__all__ = ['ParseResultCache', 'PARSER_VERSION', 'sha256_hex', 'AGENT_ID', 'KIND']
