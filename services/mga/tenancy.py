"""Binder / entity tenancy keys (ERP/MGA integrity U13).

Historical rows default to the platform binder and entity. New remittance /
bordereaux / trust / cession rows carry ``binder_id`` in payload. The platform
ledger chain stays one chain — binder is a payload key, never a second ledger.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

DEFAULT_BINDER_ID = 'PHINS-DEFAULT'
DEFAULT_ENTITY_ID = 'PHINS-PLATFORM'


def normalize_binder_id(value: Any) -> str:
    raw = str(value or '').strip()
    return raw or DEFAULT_BINDER_ID


def normalize_entity_id(value: Any) -> str:
    raw = str(value or '').strip()
    return raw or DEFAULT_ENTITY_ID


def stamp_tenancy(record: Optional[Mapping[str, Any]], *, binder_id: Any = None, entity_id: Any = None) -> Dict[str, Any]:
    """Return a copy with binder/entity defaults filled (never invent cash)."""
    out = dict(record or {})
    out['binder_id'] = normalize_binder_id(
        binder_id if binder_id is not None else out.get('binder_id')
    )
    out['entity_id'] = normalize_entity_id(
        entity_id if entity_id is not None else out.get('entity_id')
    )
    return out


def same_binder(left: Any, right: Any) -> bool:
    return normalize_binder_id(left) == normalize_binder_id(right)


def assert_binder_scope(
    resource: Mapping[str, Any],
    *,
    binder_id: Any,
    resource_label: str = 'resource',
) -> None:
    """Raise ``PermissionError`` when the resource binder differs from the scope."""
    wanted = normalize_binder_id(binder_id)
    got = normalize_binder_id(resource.get('binder_id'))
    if got != wanted:
        raise PermissionError(
            f'cross_binder_refused:{resource_label}:wanted={wanted}:got={got}'
        )


def filter_by_binder(items: Mapping[str, Any] | list, binder_id: Any) -> Dict[str, Any]:
    """Keep only rows whose binder matches (missing binder → platform default)."""
    wanted = normalize_binder_id(binder_id)
    if isinstance(items, Mapping):
        rows = items.items()
        return {
            key: stamp_tenancy(val) for key, val in rows
            if same_binder((val or {}).get('binder_id') if isinstance(val, Mapping) else None, wanted)
        }
    out = {}
    for idx, val in enumerate(items or []):
        if isinstance(val, Mapping) and same_binder(val.get('binder_id'), wanted):
            out[str(val.get('id') or idx)] = stamp_tenancy(val)
    return out


__all__ = [
    'DEFAULT_BINDER_ID',
    'DEFAULT_ENTITY_ID',
    'assert_binder_scope',
    'filter_by_binder',
    'normalize_binder_id',
    'normalize_entity_id',
    'same_binder',
    'stamp_tenancy',
]
