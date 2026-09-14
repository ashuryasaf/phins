"""
Durable agent state with a read-through cache (A4).

Agents keep their working artifacts (probability reports, assessments,
analyses, video jobs) in process memory. That loses them on restart and makes
multi-instance deployments disagree. AgentOS solved this once with a
TTL-coalesced re-hydration of durable tables; this module lifts that pattern
out so every agent can use it:

* :class:`RefreshCoalescer` — the TTL gate: at most one refresh per
  ``PHINS_AGENT_HYDRATE_TTL`` seconds on the read path, always on the write
  path. Extracted verbatim from ``agent_ecosystem_service``.
* :class:`HydratedStore` — a ``MutableMapping`` whose truth is a durable
  table when the platform runs database-backed and a plain dict otherwise.
  Reads re-hydrate (coalesced, incremental by ``updated_date`` with a
  periodic full resync so peers' deletions are seen too); writes go to the
  table first and then force a refresh, so a caller never reads its own write
  back stale. Every fallible step happens in local structures before the
  cache is swapped, so a mid-refresh failure can never leave an emptied or
  half-loaded cache.
* :func:`to_jsonable` / :func:`from_jsonable` — a lossless codec for the
  nested ``@dataclass`` / ``Enum`` / ``datetime`` records the bots produce, so
  a row round-trips to the exact object the agent built (``to_dict`` on those
  classes is a rounded presentation view, not a storage format).

Integrity rules: the durable write happens before the in-memory write and a
failed durable write is reported (``on_error``) rather than silently turned
into a memory-only record; the store never invents or repairs rows.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import sys
import threading
import time
import typing
from collections.abc import MutableMapping
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Iterable, Iterator, Optional, Tuple

logger = logging.getLogger(__name__)

HYDRATE_TTL_ENV = 'PHINS_AGENT_HYDRATE_TTL'
FULL_RESYNC_ENV = 'PHINS_AGENT_FULL_RESYNC_SECONDS'
DEFAULT_TTL = 1.5
DEFAULT_FULL_RESYNC = 60.0


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def db_mode_enabled() -> bool:
    """Whether durable agent state is on.

    Defers to the portal's *effective* runtime mode when the server module is
    loaded (``web_portal/server.py`` can disable database mode at runtime after
    a connection failure while ``USE_DATABASE`` stays set); falls back to the
    env var for isolated use (workers, tests). Same rule as AgentOS.
    """
    portal = sys.modules.get('web_portal.server')
    if portal is not None and hasattr(portal, 'USE_DATABASE'):
        return bool(getattr(portal, 'USE_DATABASE', False)
                    and getattr(portal, 'database_enabled', False))
    return os.environ.get('USE_DATABASE', 'true').lower() not in ('false', '0', 'no')


class RefreshCoalescer:
    """At most one refresh per ``ttl`` seconds unless forced.

    ``due(force)`` answers whether a refresh should run now; ``mark()`` records
    that one ran; ``reset()`` makes the next call due immediately (used after
    writes and by tests). Thread-safe.
    """

    def __init__(self, ttl: Optional[float] = None):
        self._ttl = DEFAULT_TTL if ttl is None else float(ttl)
        self._last = 0.0
        self._lock = threading.Lock()

    @property
    def ttl(self) -> float:
        return self._ttl

    @property
    def last_refresh(self) -> float:
        return self._last

    def due(self, force: bool = False) -> bool:
        if force:
            return True
        with self._lock:
            return (time.monotonic() - self._last) >= self._ttl

    def mark(self) -> None:
        with self._lock:
            self._last = time.monotonic()

    def reset(self) -> None:
        with self._lock:
            self._last = 0.0


# --------------------------------------------------------------------------
# Lossless dataclass codec
# --------------------------------------------------------------------------

def to_jsonable(value: Any) -> Any:
    """Recursively convert dataclasses/enums/datetimes into JSON-safe data."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    return value


def _unwrap_optional(tp: Any) -> Tuple[Any, bool]:
    origin = typing.get_origin(tp)
    if origin is typing.Union:
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
    return tp, False


def from_jsonable(tp: Any, data: Any) -> Any:
    """Inverse of :func:`to_jsonable` guided by a type annotation.

    Handles nested dataclasses, ``Enum`` subclasses, ``datetime``,
    ``List[X]``, ``Dict[K, V]``, ``Optional[X]`` and leaves ``Any``/unknown
    types untouched. Unknown keys on a dataclass are ignored so an older row
    still loads after a field is removed; missing keys fall back to the field
    default.
    """
    if data is None:
        return None
    tp, _ = _unwrap_optional(tp)
    if tp is Any or isinstance(tp, typing.TypeVar):
        return data
    if isinstance(tp, str):  # unresolved forward reference
        return data
    if dataclasses.is_dataclass(tp) and isinstance(data, dict):
        hints = typing.get_type_hints(tp)
        kwargs = {}
        for f in dataclasses.fields(tp):
            if f.name in data:
                kwargs[f.name] = from_jsonable(hints.get(f.name, Any), data[f.name])
        return tp(**kwargs)
    if isinstance(tp, type) and issubclass(tp, Enum):
        return data if isinstance(data, tp) else tp(data)
    if tp is datetime:
        return data if isinstance(data, datetime) else datetime.fromisoformat(str(data))
    origin = typing.get_origin(tp)
    if origin in (list, tuple, set) and isinstance(data, (list, tuple)):
        args = typing.get_args(tp)
        inner = args[0] if args else Any
        converted = [from_jsonable(inner, v) for v in data]
        return origin(converted) if origin is not list else converted
    if origin is dict and isinstance(data, dict):
        args = typing.get_args(tp)
        val_tp = args[1] if len(args) == 2 else Any
        return {k: from_jsonable(val_tp, v) for k, v in data.items()}
    return data


# --------------------------------------------------------------------------
# HydratedStore
# --------------------------------------------------------------------------

# loader(since) -> iterable of (key, value, updated_at); ``since=None`` means
# the full table. ``updated_at`` may be None when the source has no clock.
Loader = Callable[[Optional[datetime]], Iterable[Tuple[str, Any, Optional[datetime]]]]
Saver = Callable[[str, Any], None]
Deleter = Callable[[str], None]


class HydratedStore(MutableMapping):
    """Keyed agent state: durable table when DB mode is on, dict otherwise.

    ``loader``, ``saver`` and ``deleter`` are the only things that touch the
    database, so a consumer decides its own table shape and codec. ``enabled``
    is re-evaluated on every operation (the portal can drop DB mode at runtime).
    """

    def __init__(self, name: str, *, loader: Loader, saver: Saver,
                 deleter: Optional[Deleter] = None, ttl: Optional[float] = None,
                 full_resync_interval: Optional[float] = None,
                 enabled: Callable[[], bool] = db_mode_enabled,
                 on_error: Optional[Callable[[str, Exception], None]] = None):
        self.name = name
        self._loader = loader
        self._saver = saver
        self._deleter = deleter
        self._enabled = enabled
        self._on_error = on_error
        self._coalescer = RefreshCoalescer(
            _env_float(HYDRATE_TTL_ENV, DEFAULT_TTL) if ttl is None else ttl)
        self._full_resync = (_env_float(FULL_RESYNC_ENV, DEFAULT_FULL_RESYNC)
                             if full_resync_interval is None else float(full_resync_interval))
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = {}
        self._watermark: Optional[datetime] = None
        self._last_full = 0.0
        self._hydrated_once = False
        # Keys whose durable write failed: kept across full resyncs (reported,
        # never silently dropped) until a later write for the key succeeds.
        self._unsaved: set = set()
        self.stats = {'hydrations': 0, 'full_hydrations': 0, 'rows_loaded': 0,
                      'writes': 0, 'deletes': 0, 'errors': 0}

    # -- introspection -----------------------------------------------------
    @property
    def durable(self) -> bool:
        try:
            return bool(self._enabled())
        except Exception:
            return False

    @property
    def coalescer(self) -> RefreshCoalescer:
        return self._coalescer

    def _report(self, what: str, exc: Exception) -> None:
        self.stats['errors'] += 1
        logger.warning("hydrated_store[%s] %s failed: %s", self.name, what, exc)
        if self._on_error is not None:
            try:
                self._on_error(what, exc)
            except Exception:
                pass

    # -- hydration -----------------------------------------------------------
    def hydrate(self, force: bool = False) -> bool:
        """Refresh the cache from the table. Returns True when a load ran.

        Incremental (rows with ``updated_at >= watermark``) between full
        resyncs; the first load and every ``full_resync_interval`` seconds do a
        full replace so peer deletions are reflected. Best-effort: a loader
        failure keeps the current cache and is retried on the next call.
        """
        if not self.durable:
            return False
        if not self._coalescer.due(force):
            return False
        with self._lock:
            if not self._coalescer.due(force):
                return False
            now = time.monotonic()
            full = (not self._hydrated_once or self._watermark is None
                    or (now - self._last_full) >= self._full_resync)
            since = None if full else self._watermark
            try:
                rows = list(self._loader(since))
            except Exception as exc:
                self._report('hydrate', exc)
                return False
            fresh: Dict[str, Any] = {}
            newest = self._watermark
            for key, value, updated_at in rows:
                fresh[str(key)] = value
                if updated_at is not None and (newest is None or updated_at > newest):
                    newest = updated_at
            if full:
                for key in self._unsaved:
                    if key in self._data and key not in fresh:
                        fresh[key] = self._data[key]
                self._data = fresh
                self._last_full = now
                self.stats['full_hydrations'] += 1
            else:
                self._data.update(fresh)
            self._watermark = newest
            self._hydrated_once = True
            self.stats['hydrations'] += 1
            self.stats['rows_loaded'] += len(rows)
            self._coalescer.mark()
            return True

    def reset(self) -> None:
        """Drop the cache and watermark (simulates a fresh process; tests)."""
        with self._lock:
            self._data.clear()
            self._watermark = None
            self._last_full = 0.0
            self._hydrated_once = False
            self._unsaved.clear()
            self._coalescer.reset()

    # -- MutableMapping ------------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        self.hydrate()
        with self._lock:
            return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        self.hydrate()
        with self._lock:
            return self._data.get(key, default)

    def __contains__(self, key: object) -> bool:
        self.hydrate()
        with self._lock:
            return key in self._data

    def __iter__(self) -> Iterator[str]:
        self.hydrate()
        with self._lock:
            return iter(list(self._data.keys()))

    def __len__(self) -> int:
        self.hydrate()
        with self._lock:
            return len(self._data)

    def keys(self):
        self.hydrate()
        with self._lock:
            return list(self._data.keys())

    def values(self):
        self.hydrate()
        with self._lock:
            return list(self._data.values())

    def items(self):
        self.hydrate()
        with self._lock:
            return list(self._data.items())

    def __setitem__(self, key: str, value: Any) -> None:
        self.put(key, value)

    def put(self, key: str, value: Any, *, persist: bool = True) -> None:
        """Write-through: table first (when durable), then cache, then refresh.

        ``persist=False`` updates only the cache — for callers that already
        performed the durable write themselves (e.g. a conditional UPDATE).
        """
        key = str(key)
        durable = self.durable and persist
        saved = False
        if durable:
            try:
                self._saver(key, value)
                self.stats['writes'] += 1
                saved = True
            except Exception as exc:
                self._report(f'save {key}', exc)
        with self._lock:
            self._data[key] = value
            if durable and not saved:
                self._unsaved.add(key)
            elif saved:
                self._unsaved.discard(key)
        # Refresh only after a successful durable write; a failed one leaves a
        # reported memory-only record (pre-A4 behaviour) that resyncs keep.
        if saved:
            self.hydrate(force=True)

    def set_local(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[str(key)] = value

    def __delitem__(self, key: str) -> None:
        with self._lock:
            if key not in self._data:
                self.hydrate(force=True)
                if key not in self._data:
                    raise KeyError(key)
        self._delete(key)

    def pop(self, key: str, default: Any = dataclasses.MISSING) -> Any:
        self.hydrate()
        with self._lock:
            present = key in self._data
            value = self._data.get(key)
        if not present:
            if default is dataclasses.MISSING:
                raise KeyError(key)
            return default
        self._delete(key)
        return value

    def _delete(self, key: str) -> None:
        key = str(key)
        if self.durable and self._deleter is not None:
            try:
                self._deleter(key)
                self.stats['deletes'] += 1
            except Exception as exc:
                self._report(f'delete {key}', exc)
        with self._lock:
            self._data.pop(key, None)
            self._unsaved.discard(key)

    def clear(self) -> None:
        """Clear the cache only. Durable rows are never bulk-deleted from here."""
        with self._lock:
            self._data.clear()

    def snapshot(self) -> Dict[str, Any]:
        """Health view for ``/api/admin/ai-agents/health``-style surfaces."""
        with self._lock:
            return {
                'name': self.name,
                'durable': self.durable,
                'cached': len(self._data),
                'ttl_seconds': self._coalescer.ttl,
                'full_resync_seconds': self._full_resync,
                'watermark': self._watermark.isoformat() if self._watermark else None,
                'unsaved': len(self._unsaved),
                **self.stats,
            }


__all__ = [
    'DEFAULT_FULL_RESYNC', 'DEFAULT_TTL', 'FULL_RESYNC_ENV', 'HYDRATE_TTL_ENV',
    'HydratedStore', 'RefreshCoalescer', 'db_mode_enabled', 'from_jsonable', 'to_jsonable',
]
