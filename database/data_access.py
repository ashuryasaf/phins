"""
Data Access Layer

Provides backward-compatible dictionary-like interface to database.
This allows gradual migration from in-memory to database storage.

IMPORTANT: This module includes automatic connection recovery. When database
operations fail due to connection issues, it will attempt to retry with
reconnection logic.
"""

import os
from typing import Dict, Any, Optional, List
from datetime import datetime
from sqlalchemy.exc import OperationalError, DatabaseError, DisconnectionError
import logging
import time

from database.manager import DatabaseManager

logger = logging.getLogger(__name__)

# Retry configuration for database operations
MAX_RETRIES = 3
RETRY_DELAY = 0.5  # seconds

# Cache freshness window for DatabaseDict bulk reads (values()/items()/keys()).
# This prevents stale reads when another process or replica writes to the DB.
# Without a TTL, an admin GET /api/claims that ran early would never see new
# customer-filed claims persisted by a different process — exactly the
# "claim made but not pushed to admin/dashboard" symptom reported on prod.
# Override with DATABASE_DICT_CACHE_TTL_SECONDS (set to 0 to disable caching).
def _resolve_cache_ttl_seconds() -> float:
    raw = os.environ.get('DATABASE_DICT_CACHE_TTL_SECONDS')
    if raw is None or raw == '':
        return 5.0
    try:
        value = float(raw)
        return value if value >= 0 else 5.0
    except (TypeError, ValueError):
        return 5.0


DATABASE_DICT_CACHE_TTL_SECONDS: float = _resolve_cache_ttl_seconds()

# Write listeners: ``fn(repository_name, operation)`` runs after every
# successful DatabaseDict write ('set' | 'delete' | 'clear'). Used by derived
# read models (BI dashboards) to learn that their inputs may have changed
# without polling. A listener that raises never breaks the write.
_WRITE_LISTENERS: List[Any] = []


def add_write_listener(listener) -> None:
    if listener not in _WRITE_LISTENERS:
        _WRITE_LISTENERS.append(listener)


def remove_write_listener(listener) -> None:
    try:
        _WRITE_LISTENERS.remove(listener)
    except ValueError:
        pass


def _notify_write(repository_name: str, operation: str) -> None:
    for listener in list(_WRITE_LISTENERS):
        try:
            listener(repository_name, operation)
        except Exception as exc:  # never let a derived-view hook break a write
            logger.warning("DatabaseDict write listener failed for %s/%s: %s",
                           repository_name, operation, exc)


def _parse_datetime_value(value: Any) -> Any:
    """Parse an ISO / date string into ``datetime``; leave other values alone."""
    if value is None or isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        pass
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%d/%m/%Y'):
        try:
            return datetime.strptime(text[:10], fmt)
        except (ValueError, TypeError):
            continue
    return value


_DATETIME_FIELD_NAMES = (
    'created_date', 'updated_date', 'start_date', 'end_date',
    'approval_date', 'filed_date', 'payment_date', 'submitted_date',
    'decision_date', 'due_date', 'paid_date', 'expires', 'last_login',
    'timestamp',
)

_JSON_FIELD_NAMES = (
    'questionnaire_responses', 'payment_setup', 'health_wallet',
    'billing', 'riders', 'metadata', 'additional_data',
    'medical_conditions', 'documents', 'data_sources',
)


def convert_datetime_strings(data: Dict[str, Any], *, stringify_json: bool = True) -> Dict[str, Any]:
    """
    Convert ISO datetime strings to datetime objects and dict fields to JSON strings.
    
    Args:
        data: Dictionary that may contain datetime strings and nested dicts
        stringify_json: When False, leave dict/list JSON fields alone so
            ``pack_row_extra`` can seal non-column keys without double-encoding
            them as strings (U3 dual-path).
    
    Returns:
        Dictionary with datetime strings converted to datetime objects
        and dict fields converted to JSON strings
    """
    import json
    
    result = data.copy()
    
    # Convert datetime fields
    for field in _DATETIME_FIELD_NAMES:
        if field in result and result[field] is not None:
            result[field] = _parse_datetime_value(result[field])
    
    if not stringify_json:
        return result

    # Convert dict/list fields to JSON strings for storage
    for field in _JSON_FIELD_NAMES:
        if field in result and result[field] is not None:
            value = result[field]
            if isinstance(value, (dict, list)):
                try:
                    result[field] = json.dumps(value)
                except (TypeError, ValueError):
                    # If JSON encoding fails, try str
                    result[field] = str(value)
    
    return result


def stringify_json_columns(model_class, data: Dict[str, Any]) -> Dict[str, Any]:
    """JSON-encode dict/list values only for columns that store Text JSON."""
    import json

    try:
        columns = {c.name for c in model_class.__table__.columns}
    except Exception:
        columns = set()
    result = data
    for field in _JSON_FIELD_NAMES:
        if field not in columns or field not in result or result[field] is None:
            continue
        value = result[field]
        if isinstance(value, (dict, list)):
            if result is data:
                result = data.copy()
            try:
                result[field] = json.dumps(value)
            except (TypeError, ValueError):
                result[field] = str(value)
    return result


def coerce_model_datetimes(model_class, data: Dict[str, Any]) -> Dict[str, Any]:
    """Re-parse every DateTime column so SQLite/Postgres never see raw strings."""
    try:
        from sqlalchemy import DateTime as SADateTime
        columns = model_class.__table__.columns
    except Exception:
        return data
    result = data
    for column in columns:
        name = column.name
        if name not in result or result[name] is None:
            continue
        try:
            if not isinstance(column.type, SADateTime):
                continue
        except Exception:
            continue
        parsed = _parse_datetime_value(result[name])
        if parsed is not result[name]:
            if result is data:
                result = data.copy()
            result[name] = parsed
    return result


def _test_mode_enabled() -> bool:
    return os.environ.get('PHINS_TEST_MODE', '').lower() in ('1', 'true', 'yes')


def ensure_fk_parents(repository_name: str, data: Dict[str, Any]) -> None:
    """Seed missing FK parents under ``PHINS_TEST_MODE`` only.

    In-memory stores have no relational order; Postgres rejects a policy
    whose customer row is not yet inserted. Dual-path fixtures often assign
    ``POLICIES[pid]`` before ``CUSTOMERS[cid]``. Production writers create
    parents first — this helper must never run outside tests.
    """
    if not _test_mode_enabled():
        return
    if repository_name == 'policies':
        cid = data.get('customer_id')
        if cid:
            customers = DatabaseDict('customers')
            if cid not in customers:
                customers[cid] = {'id': cid, 'name': str(cid)}
    elif repository_name == 'claims':
        cid = data.get('customer_id')
        pid = data.get('policy_id')
        if cid:
            customers = DatabaseDict('customers')
            if cid not in customers:
                customers[cid] = {'id': cid, 'name': str(cid)}
        if pid:
            policies = DatabaseDict('policies')
            if pid not in policies:
                policies[pid] = {
                    'id': pid,
                    'customer_id': cid or 'CUST-UNASSIGNED',
                    'type': 'life',
                    'coverage_amount': 0.0,
                    'annual_premium': 0.0,
                }


def apply_create_defaults(repository_name: str, key: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Fill NOT NULL columns the in-memory dict shape often omits.

    Test-only. Production API writers already send these fields; inventing
    ``{id}@phins.local`` or ``POL-UNASSIGNED`` on a live create would land
    placeholder rows in the books. Under ``PHINS_TEST_MODE`` the defaults are
    deterministic per id so a retry does not invent a new email.
    """
    import re

    if not _test_mode_enabled():
        return data

    result = data
    changed = False

    def _set(name, value):
        nonlocal result, changed
        if result is data:
            result = data.copy()
        result[name] = value
        changed = True

    if repository_name == 'customers':
        name = result.get('name')
        if name is None or (isinstance(name, str) and not name.strip()):
            _set('name', str(key))
        if not result.get('email'):
            slug = re.sub(r'[^a-zA-Z0-9]+', '-', str(key).lower()).strip('-') or 'customer'
            _set('email', f'{slug}@phins.local')
    elif repository_name == 'policies':
        if not result.get('type'):
            _set('type', result.get('policy_type') or result.get('product_type') or 'life')
        if result.get('coverage_amount') is None:
            coverage = None
            for alt in ('coverage', 'sum_insured', 'face_amount'):
                if result.get(alt) is not None:
                    try:
                        coverage = float(result[alt])
                    except (TypeError, ValueError):
                        coverage = None
                    if coverage is not None:
                        break
            if coverage is None:
                try:
                    coverage = float(result.get('annual_premium') or 0.0)
                except (TypeError, ValueError):
                    coverage = 0.0
            _set('coverage_amount', coverage)
        if result.get('annual_premium') is None:
            _set('annual_premium', 0.0)
    elif repository_name == 'billing':
        if result.get('amount') is None and result.get('amount_due') is not None:
            try:
                _set('amount', float(result['amount_due']))
            except (TypeError, ValueError):
                _set('amount', 0.0)
        if result.get('amount') is None and result.get('amount_paid') is not None:
            try:
                _set('amount', float(result['amount_paid']))
            except (TypeError, ValueError):
                pass
        if result.get('amount') is None:
            _set('amount', 0.0)
    elif repository_name == 'claims':
        if result.get('claimed_amount') is None and result.get('amount') is not None:
            try:
                _set('claimed_amount', float(result['amount']))
            except (TypeError, ValueError):
                _set('claimed_amount', 0.0)
        if result.get('claimed_amount') is None:
            _set('claimed_amount', 0.0)
        # Wallet-repair fixtures often omit policy_id; keep a stable placeholder
        # so the dual-path row lands (in-memory dicts allow the omission).
        if not result.get('policy_id'):
            _set('policy_id', 'POL-UNASSIGNED')
        if not result.get('customer_id'):
            _set('customer_id', 'CUST-UNASSIGNED')
    return result


_EXTRA_REPOSITORIES = frozenset({
    'customers', 'policies', 'claims', 'billing', 'underwriting',
})
_EXTRA_ALIASES = {
    'billing': frozenset({'amount_due', 'bill_id'}),
    'claims': frozenset({'amount', 'claim_id', 'files'}),
    'policies': frozenset({'policy_id', 'policy_type', 'product_type', 'coverage', 'sum_insured', 'face_amount'}),
    'underwriting': frozenset({'uw_id', 'application_id'}),
}


def pack_row_extra(repository_name: str, model_class, data: Dict[str, Any], existing: Any = None) -> Dict[str, Any]:
    """Seal non-column keys into ``extra`` so dual-path reads keep them.

    Kernel-pin fields stay on ``kernel_pin`` for policies. Mapped aliases are
    not stored twice. A broken existing overlay is replaced, never merged.
    """
    import json

    if repository_name not in _EXTRA_REPOSITORIES:
        return data
    try:
        columns = {c.name for c in model_class.__table__.columns}
    except Exception:
        return data
    if 'extra' not in columns:
        return data

    reserved = set(columns)
    reserved.update(_EXTRA_ALIASES.get(repository_name, ()))
    if repository_name == 'policies':
        from database.models import POLICY_KERNEL_PIN_FIELDS
        reserved.update(POLICY_KERNEL_PIN_FIELDS)

    extras: Dict[str, Any] = {}
    if existing is not None:
        raw = getattr(existing, 'extra', None)
        if raw not in (None, ''):
            try:
                loaded = raw if isinstance(raw, dict) else json.loads(raw)
                if isinstance(loaded, dict):
                    extras.update(loaded)
            except Exception:
                extras = {}

    for key, value in data.items():
        if key in reserved or key == 'extra':
            continue
        if value is None:
            extras.pop(key, None)
        else:
            extras[key] = value

    result = data.copy()
    if extras:
        try:
            result['extra'] = json.dumps(extras, sort_keys=True, default=str)
        except (TypeError, ValueError):
            result['extra'] = json.dumps({k: str(v) for k, v in extras.items()}, sort_keys=True)
    else:
        result['extra'] = None
    return result


class _NestedWriteThrough(dict):
    """Nested dict that assign-backs into a parent ``_WriteThroughRecord``.

    The new mapping is built aside and adopted only after that assign-back
    persists. Mutating this proxy first would make the parent's rollback
    snapshot the new value, so a failed write would leave the proxy ahead
    of the database. (Autofix ``1bbc092875``, absorbed onto tip.)
    """

    __slots__ = ('_parent', '_parent_key')

    def __init__(self, parent: '_WriteThroughRecord', parent_key: str, data: Dict[str, Any]):
        super().__init__(data)
        self._parent = parent
        self._parent_key = parent_key

    def _commit(self, pending: Dict[str, Any]) -> None:
        """Assign ``pending`` back, then adopt it only if that persist succeeds."""
        self._parent[self._parent_key] = pending
        super().clear()
        super().update(pending)

    def __setitem__(self, key, value):
        pending = dict(self)
        pending[key] = value
        self._commit(pending)

    def __delitem__(self, key):
        pending = dict(self)
        del pending[key]
        self._commit(pending)

    def clear(self):
        self._commit({})

    def pop(self, *args):
        pending = dict(self)
        value = pending.pop(*args)
        self._commit(pending)
        return value

    def popitem(self):
        pending = dict(self)
        item = pending.popitem()
        self._commit(pending)
        return item

    def setdefault(self, key, default=None):
        if key in self:
            return self[key]
        pending = dict(self)
        pending.setdefault(key, default)
        self._commit(pending)
        return self[key]

    def update(self, *args, **kwargs):
        pending = dict(self)
        pending.update(*args, **kwargs)
        self._commit(pending)


class _WriteThroughRecord(dict):
    """Dict returned by ``DatabaseDict.__getitem__`` that persists edits.

    In-memory stores return a live reference; DatabaseDict used to return a
    detached ``to_dict`` copy so ``store[id]['x'] = y`` was silently lost.
    One level of nested dict mutation (``store[id]['health_wallet']['x']=y``)
    assign-backs through ``_NestedWriteThrough``.

    Intentional under U3 dual-path: production writers mutate nested fields
    (e.g. ``health_wallet.written_distribution``) the same way as in-memory.
    Each edit reassigns ``store[key]`` so ``DatabaseDict.__setitem__`` commits
    once; a failed persist raises and does not leave a silent split brain.
    """

    __slots__ = ('_store', '_key', '_persisting')

    def __init__(self, store: 'DatabaseDict', key: str, data: Dict[str, Any]):
        super().__init__(data)
        self._store = store
        self._key = key
        self._persisting = False

    def _snapshot(self) -> Dict[str, Any]:
        return {
            k: (dict(v) if isinstance(v, _NestedWriteThrough) else v)
            for k, v in self.items()
        }

    def _restore(self, snapshot: Dict[str, Any]) -> None:
        super().clear()
        super().update(snapshot)

    def _persist(self) -> None:
        if self._persisting:
            return
        self._persisting = True
        try:
            # Nested proxies must flatten to plain dicts before the DB write.
            self._store[self._key] = self._snapshot()
        finally:
            self._persisting = False

    def _mutate_then_persist(self, apply) -> Any:
        """Apply ``apply`` then persist; roll the proxy back if the DB write fails."""
        before = self._snapshot()
        try:
            result = apply()
            self._persist()
            return result
        except Exception:
            self._restore(before)
            raise

    def __getitem__(self, key):
        value = super().__getitem__(key)
        if isinstance(value, dict) and not isinstance(value, (_WriteThroughRecord, _NestedWriteThrough)):
            wrapped = _NestedWriteThrough(self, key, value)
            # Install the wrapper without triggering a DB write.
            super().__setitem__(key, wrapped)
            return wrapped
        return value

    def __setitem__(self, key, value):
        if isinstance(value, _NestedWriteThrough):
            value = dict(value)

        def apply():
            super(_WriteThroughRecord, self).__setitem__(key, value)

        self._mutate_then_persist(apply)

    def __delitem__(self, key):
        def apply():
            super(_WriteThroughRecord, self).__delitem__(key)

        self._mutate_then_persist(apply)

    def clear(self):
        def apply():
            super(_WriteThroughRecord, self).clear()

        self._mutate_then_persist(apply)

    def pop(self, *args):
        def apply():
            return super(_WriteThroughRecord, self).pop(*args)

        return self._mutate_then_persist(apply)

    def popitem(self):
        def apply():
            return super(_WriteThroughRecord, self).popitem()

        return self._mutate_then_persist(apply)

    def setdefault(self, key, default=None):
        if key in self:
            return self[key]

        def apply():
            super(_WriteThroughRecord, self).setdefault(key, default)
            return self[key]

        return self._mutate_then_persist(apply)

    def update(self, *args, **kwargs):
        def apply():
            super(_WriteThroughRecord, self).update(*args, **kwargs)

        self._mutate_then_persist(apply)


# Field mappings from server dictionary keys to database model fields
# This ensures backward compatibility with existing code that uses different key names
FIELD_MAPPINGS = {
    'billing': {
        'bill_id': 'id',           # bill_id → id (database uses 'id' as primary key)
        'amount_due': 'amount',    # amount_due → amount
    },
    'claims': {
        'claim_id': 'id',          # claim_id → id
        'files': 'files_metadata', # files → files_metadata (stored as JSON string)
    },
    'policies': {
        'policy_id': 'id',         # policy_id → id (if used)
    },
    'underwriting': {
        'uw_id': 'id',             # uw_id → id (if used)
        'application_id': 'id',    # application_id → id
    }
}

# Fields that need JSON serialization when storing
JSON_FIELDS = {
    'claims': ['files_metadata', 'bank_details'],
}


def map_fields_for_repository(repository_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map field names from server dictionary format to database model format.
    Also handles JSON serialization for complex fields.
    
    Args:
        repository_name: Name of the repository (billing, claims, etc.)
        data: Dictionary with server field names
    
    Returns:
        Dictionary with database model field names
    """
    import json
    
    result = data.copy()
    
    # Apply field name mappings
    mappings = FIELD_MAPPINGS.get(repository_name, {})
    for old_name, new_name in mappings.items():
        if old_name in result:
            # Copy value to new field name
            if new_name not in result:  # Don't overwrite if already present
                result[new_name] = result[old_name]
            # Remove old field name (to avoid 'unexpected keyword argument' errors)
            del result[old_name]
    
    # Serialize JSON fields (convert dicts/lists to JSON strings)
    json_fields = JSON_FIELDS.get(repository_name, [])
    for field in json_fields:
        if field in result and result[field] is not None:
            if isinstance(result[field], (dict, list)):
                result[field] = json.dumps(result[field])
    
    return result


def _seal_policy_kernel_pin(key: str, value: Dict[str, Any], existing: Any) -> None:
    """Carry a policy's kernel pin into the sealed ``kernel_pin`` column.

    The pin keys are not columns, so without this they are dropped on write
    and every later premium books as pure risk. A write that names only some
    keys keeps the rest, and a key written as ``None`` is cleared. A stored
    pin whose checksum does not match is left as it is: it is not overwritten
    and the new keys are not written.
    """
    from database.models import (
        POLICY_KERNEL_PIN_FIELDS,
        pack_policy_kernel_pin,
        policy_kernel_pin_fields,
        unpack_policy_kernel_pin,
    )

    value.pop('kernel_pin', None)
    incoming = policy_kernel_pin_fields(value)
    cleared = [name for name in POLICY_KERNEL_PIN_FIELDS if name in value and value[name] is None]
    stored: Dict[str, Any] = {}
    if existing is not None:
        stored, intact = unpack_policy_kernel_pin(getattr(existing, 'kernel_pin', None))
        if not intact:
            logger.error(
                "Policy %s kernel pin failed its checksum; the stored pin is left unchanged", key
            )
            return
    merged = {**stored, **incoming}
    for name in cleared:
        merged.pop(name, None)
    if merged != stored:
        value['kernel_pin'] = pack_policy_kernel_pin(merged) if merged else None


class DatabaseDict:
    """
    Dictionary-like wrapper around database repository.
    Provides dict API for backward compatibility with existing code.
    
    Includes automatic retry logic for connection failures.
    """
    
    def __init__(self, repository_name: str):
        """
        Initialize database dict wrapper.
        
        Args:
            repository_name: Name of repository (customers, policies, claims, etc.)
        """
        self.repository_name = repository_name
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_valid = False
        # Monotonic timestamp (seconds) of the most recent successful cache
        # refresh. Used together with DATABASE_DICT_CACHE_TTL_SECONDS so that
        # bulk reads (values()/items()/keys()/iter) never return data older
        # than the configured freshness window. This is what makes a claim
        # filed on Process A visible to an admin GET on Process B without
        # having to wait for an unrelated write to invalidate the cache.
        self._cache_loaded_at: float = 0.0
        # Bumped whenever the content this dict exposes may differ from what
        # a reader last saw: on every local write and on every refresh that
        # loaded different rows (another process wrote). Readers that cache
        # something derived from the whole store (BI fingerprints) key it on
        # this number instead of re-hashing every row.
        self._content_version: int = 0

    def content_version(self) -> int:
        """Freshness-checked content version.

        Refreshes the bulk cache first when its TTL has elapsed, so a caller
        that skips its own full scan because the version is unchanged still
        observes rows written by another process within
        ``DATABASE_DICT_CACHE_TTL_SECONDS`` — the same window ``values()``
        honours.
        """
        if not self._is_cache_fresh():
            self._refresh_cache()
        return self._content_version

    def _bump_content_version(self) -> None:
        self._content_version += 1

    def _is_cache_fresh(self) -> bool:
        """Return True if the cache is both marked valid and within the TTL."""
        if not self._cache_valid:
            return False
        ttl = DATABASE_DICT_CACHE_TTL_SECONDS
        if ttl <= 0:
            # TTL disabled -> always treat valid cache as stale so reads hit DB.
            return False
        return (time.monotonic() - self._cache_loaded_at) < ttl

    def invalidate_cache(self) -> None:
        """Public hook to force the next bulk read to refresh from the DB."""
        self._cache_valid = False
        self._cache_loaded_at = 0.0
    
    def _get_repository(self, db: DatabaseManager):
        """Get the appropriate repository from database manager"""
        return getattr(db, self.repository_name)
    
    def _execute_with_retry(self, operation, *args, **kwargs):
        """
        Execute a database operation with automatic retry on connection failures.
        
        Args:
            operation: The operation function to execute
            *args, **kwargs: Arguments to pass to the operation
        
        Returns:
            Result of the operation
        
        Raises:
            Last exception if all retries fail
        """
        last_error = None
        
        for attempt in range(MAX_RETRIES):
            try:
                return operation(*args, **kwargs)
            except (OperationalError, DatabaseError, DisconnectionError) as e:
                last_error = e
                logger.warning(f"Database operation failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                
                if attempt < MAX_RETRIES - 1:
                    sleep_time = RETRY_DELAY * (2 ** attempt)
                    logger.info(f"Retrying in {sleep_time:.1f}s...")
                    time.sleep(sleep_time)
            except Exception as e:
                # Non-connection errors - don't retry
                raise
        
        logger.error(f"Database operation failed after {MAX_RETRIES} attempts")
        raise last_error
    
    def _refresh_cache(self):
        """Refresh cache from database"""
        def _do_refresh():
            with DatabaseManager() as db:
                repo = self._get_repository(db)
                items = repo.get_all()
                def _key_for_item(item):
                    # Use correct primary key per repository (prevents subtle bugs like sessions keyed by username)
                    if self.repository_name == 'sessions' and hasattr(item, 'token'):
                        return item.token
                    if self.repository_name == 'users' and hasattr(item, 'username'):
                        return item.username
                    if hasattr(item, 'id'):
                        return item.id
                    if hasattr(item, 'username'):
                        return item.username
                    if hasattr(item, 'token'):
                        return item.token
                    return str(item)

                loaded = {_key_for_item(item): item.to_dict() for item in items}
                # Only a real content change bumps the version, so a derived
                # view is not recomputed just because the TTL elapsed.
                if not self._cache_valid or loaded != self._cache:
                    self._bump_content_version()
                self._cache = loaded
                self._cache_valid = True
                self._cache_loaded_at = time.monotonic()
        
        try:
            self._execute_with_retry(_do_refresh)
        except Exception as e:
            logger.error(f"Failed to refresh cache for {self.repository_name}: {e}")
            # Keep stale cache rather than clearing it
    
    def __getitem__(self, key: str) -> Dict[str, Any]:
        """Get item by key with automatic retry"""
        def _do_get():
            with DatabaseManager() as db:
                repo = self._get_repository(db)
                item = repo.get_by_id(key)
                if item is None:
                    raise KeyError(key)
                return item.to_dict()
        
        data = self._execute_with_retry(_do_get)
        return _WriteThroughRecord(self, key, data)
    
    def __setitem__(self, key: str, value: Dict[str, Any]):
        """Set item by key (create or update) with automatic retry"""
        if isinstance(value, _WriteThroughRecord):
            value = dict(value)
        # Datetimes only here — JSON dict fields stay dicts until after extras
        # are packed so payment_setup/billing are not double-encoded into extra.
        value = convert_datetime_strings(value, stringify_json=False)
        
        # Map field names from server format to database format
        value = map_fields_for_repository(self.repository_name, value)
        
        def _do_set():
            with DatabaseManager() as db:
                repo = self._get_repository(db)
                existing = repo.get_by_id(key)
                row_value = value
                if existing is None:
                    # Defaults only on create — never invent columns over a partial update.
                    row_value = apply_create_defaults(self.repository_name, key, value)
                    # Postgres FK: seed parents that in-memory fixtures omit.
                    ensure_fk_parents(self.repository_name, row_value)
                if self.repository_name == 'policies':
                    _seal_policy_kernel_pin(key, row_value, existing)
                value_for_row = pack_row_extra(
                    self.repository_name, repo.model_class, row_value, existing
                )
                value_for_row = stringify_json_columns(repo.model_class, value_for_row)
                value_for_row = coerce_model_datetimes(repo.model_class, value_for_row)
                if existing:
                    # Update existing - filter out keys that aren't model attributes
                    update_data = {k: v for k, v in value_for_row.items() if hasattr(existing, k)}
                    repo.update(key, **update_data)
                else:
                    # Create new (ensure id is set)
                    create_value = value_for_row.copy()
                    if 'id' not in create_value and self.repository_name not in ['users', 'sessions']:
                        create_value['id'] = key
                    elif 'username' not in create_value and self.repository_name == 'users':
                        create_value['username'] = key
                    elif 'token' not in create_value and self.repository_name == 'sessions':
                        create_value['token'] = key
                    
                    # Filter out keys that aren't valid model attributes to prevent errors
                    try:
                        model_class = repo.model_class
                        valid_columns = {c.name for c in model_class.__table__.columns}
                        filtered_value = {k: v for k, v in create_value.items() if k in valid_columns}
                        created = repo.create(**filtered_value)
                    except Exception as e:
                        # Fallback: try creating with all values
                        logger.warning(f"Error filtering columns for {self.repository_name}: {e}")
                        created = repo.create(**create_value)
                    if created is None:
                        raise RuntimeError(
                            f"DatabaseDict create failed for {self.repository_name}[{key}]"
                        )
        
        self._execute_with_retry(_do_set)
        self._cache_valid = False
        self._cache_loaded_at = 0.0
        self._bump_content_version()
        _notify_write(self.repository_name, 'set')
    
    def __delitem__(self, key: str):
        """Delete item by key with automatic retry"""
        def _do_delete():
            with DatabaseManager() as db:
                repo = self._get_repository(db)
                if not repo.delete(key):
                    raise KeyError(key)
        
        self._execute_with_retry(_do_delete)
        self._cache_valid = False
        self._cache_loaded_at = 0.0
        self._bump_content_version()
        _notify_write(self.repository_name, 'delete')
    
    def __contains__(self, key: str) -> bool:
        """Check if key exists with automatic retry"""
        def _do_contains():
            with DatabaseManager() as db:
                repo = self._get_repository(db)
                return repo.exists(key)
        
        try:
            return self._execute_with_retry(_do_contains)
        except Exception:
            # On failure, fall back to cache if available
            if self._cache_valid:
                return key in self._cache
            return False
    
    def __len__(self) -> int:
        """Get count of items with automatic retry"""
        def _do_len():
            with DatabaseManager() as db:
                repo = self._get_repository(db)
                return repo.count()
        
        try:
            return self._execute_with_retry(_do_len)
        except Exception:
            # On failure, fall back to cache if available
            if self._cache_valid:
                return len(self._cache)
            return 0
    
    def __iter__(self):
        """Iterate over keys"""
        if not self._is_cache_fresh():
            self._refresh_cache()
        return iter(self._cache)
    
    def keys(self):
        """Get all keys"""
        if not self._is_cache_fresh():
            self._refresh_cache()
        return self._cache.keys()
    
    def values(self):
        """Get all values"""
        if not self._is_cache_fresh():
            self._refresh_cache()
        return self._cache.values()
    
    def items(self):
        """Get all items"""
        if not self._is_cache_fresh():
            self._refresh_cache()
        return self._cache.items()
    
    def get(self, key: str, default=None):
        """Get item with default, with automatic retry on connection errors"""
        try:
            return self[key]
        except KeyError:
            return default
        except (OperationalError, DatabaseError, DisconnectionError) as e:
            logger.warning(f"Database error getting {self.repository_name}[{key}], returning default: {e}")
            # Try from cache if available
            if self._cache_valid and key in self._cache:
                return self._cache[key]
            return default
    
    def pop(self, key: str, *args):
        """
        Remove and return item by key.
        If key not found, return default if provided, else raise KeyError.
        
        Args:
            key: Key to remove
            *args: Optional default value
        
        Returns:
            The removed value, or default if key not found
        """
        try:
            value = self[key]
            del self[key]
            return value
        except KeyError:
            if args:
                return args[0]  # Return default
            raise
    
    def setdefault(self, key: str, default=None):
        """Get item, setting default if not present"""
        try:
            return self[key]
        except KeyError:
            self[key] = default
            return default
    
    def update(self, other=None, **kwargs):
        """Update dict with items from other dict or kwargs"""
        if other:
            if hasattr(other, 'items'):
                for k, v in other.items():
                    self[k] = v
            else:
                for k, v in other:
                    self[k] = v
        for k, v in kwargs.items():
            self[k] = v
    
    def clear(self):
        """Clear all items (USE WITH CAUTION)"""
        logger.warning(f"Clearing all {self.repository_name}")
        with DatabaseManager() as db:
            repo = self._get_repository(db)
            for item in repo.get_all():
                item_id = item.id if hasattr(item, 'id') else \
                         (item.username if hasattr(item, 'username') else \
                         (item.token if hasattr(item, 'token') else None))
                if item_id:
                    repo.delete(item_id)
        self._cache_valid = False
        self._cache_loaded_at = 0.0
        self._bump_content_version()
        _notify_write(self.repository_name, 'clear')


# Global database-backed dictionaries (backward compatible with in-memory version)
CUSTOMERS = DatabaseDict('customers')
POLICIES = DatabaseDict('policies')
CLAIMS = DatabaseDict('claims')
UNDERWRITING_APPLICATIONS = DatabaseDict('underwriting')
SESSIONS = DatabaseDict('sessions')
BILLING = DatabaseDict('billing')
USERS_DB = DatabaseDict('users')


def get_db_backed_dicts():
    """Get all database-backed dictionaries"""
    return {
        'CUSTOMERS': CUSTOMERS,
        'POLICIES': POLICIES,
        'CLAIMS': CLAIMS,
        'UNDERWRITING_APPLICATIONS': UNDERWRITING_APPLICATIONS,
        'SESSIONS': SESSIONS,
        'BILLING': BILLING,
        'USERS': USERS_DB
    }


__all__ = [
    'DatabaseDict',
    'CUSTOMERS',
    'POLICIES',
    'CLAIMS',
    'UNDERWRITING_APPLICATIONS',
    'SESSIONS',
    'BILLING',
    'USERS_DB',
    'get_db_backed_dicts',
    'add_write_listener',
    'remove_write_listener',
]
