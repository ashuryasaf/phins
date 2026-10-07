"""Durable bytes for videos and images in the media library.

Disk files are a cache. When the database is enabled, the same bytes and a
JSON record are stored in ``media_library_blobs``. The SHA-256 of the bytes
is checked on every read. A new payload is stored only when it matches the
checksum already on the row; replacing bytes is a delete followed by a new
asset. Nothing here logs payload contents or provider URLs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB_MAX_BYTES = 256 * 1024 * 1024


class MediaLibraryIntegrityError(Exception):
    """Bytes do not match the recorded checksum. Nothing was written."""


class MediaLibraryStoreError(Exception):
    """The durable store could not complete the write or delete."""


def media_db_max_bytes() -> int:
    """Largest payload stored in the database. ``0`` disables byte storage."""
    raw = os.environ.get('PHINS_MEDIA_DB_MAX_BYTES', str(_DEFAULT_DB_MAX_BYTES))
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return _DEFAULT_DB_MAX_BYTES


def _record_json(record: Dict[str, Any], asset_id: str, digest: str, size: int) -> str:
    stored = dict(record or {})
    stored['id'] = asset_id
    stored['checksum'] = digest
    stored['size'] = size
    stored['data'] = ''
    return json.dumps(stored, default=str, sort_keys=True)


def seal_asset_in_session(session: Any, asset_id: str, payload: bytes, record: Dict[str, Any]) -> str:
    """Insert or refresh one blob. Raises on an empty body or a checksum clash."""
    from database.models import MediaLibraryBlob

    asset_id = str(asset_id or '').strip()
    if not asset_id:
        raise MediaLibraryIntegrityError('media asset id is required')
    if not isinstance(payload, (bytes, bytearray)) or not payload:
        raise MediaLibraryIntegrityError('media payload is empty')
    payload = bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    declared = str((record or {}).get('checksum') or '').strip().lower()
    if declared and declared != digest:
        raise MediaLibraryIntegrityError('payload checksum does not match the asset record')

    row = session.query(MediaLibraryBlob).filter_by(asset_id=asset_id).one_or_none()
    if row is not None and str(row.sha256 or '').lower() not in ('', digest):
        raise MediaLibraryIntegrityError('refusing to replace durable media with a different checksum')

    encoded = _record_json(record or {}, asset_id, digest, len(payload))
    mime = str((record or {}).get('format') or (record or {}).get('mime_type') or 'application/octet-stream')
    mime = mime.split(';', 1)[0].strip() or 'application/octet-stream'
    asset_type = str((record or {}).get('type') or (record or {}).get('asset_type') or '')[:40]
    now = datetime.utcnow()
    if row is None:
        session.add(MediaLibraryBlob(
            asset_id=asset_id,
            sha256=digest,
            size_bytes=len(payload),
            mime_type=mime[:160],
            asset_type=asset_type,
            payload=payload,
            record_json=encoded,
            created_date=now,
            updated_date=now,
        ))
    else:
        row.sha256 = digest
        row.size_bytes = len(payload)
        row.mime_type = mime[:160]
        row.asset_type = asset_type
        row.payload = payload
        row.record_json = encoded
        row.updated_date = now
    session.commit()
    return digest


def update_record_in_session(session: Any, asset_id: str, record: Dict[str, Any], expected_sha: str) -> None:
    """Replace metadata only when the stored checksum still matches."""
    from database.models import MediaLibraryBlob

    asset_id = str(asset_id or '').strip()
    expected_sha = str(expected_sha or '').strip().lower()
    if not asset_id or not expected_sha:
        raise MediaLibraryIntegrityError('checksum is required to update a media record')
    row = session.query(MediaLibraryBlob).filter_by(asset_id=asset_id).one_or_none()
    if row is None:
        raise MediaLibraryStoreError('durable media record is missing')
    if str(row.sha256 or '').lower() != expected_sha:
        raise MediaLibraryIntegrityError('durable checksum does not match the asset record')
    size = int(row.size_bytes or 0)
    row.record_json = _record_json(record or {}, asset_id, expected_sha, size)
    mime = str((record or {}).get('format') or row.mime_type or 'application/octet-stream')
    row.mime_type = (mime.split(';', 1)[0].strip() or 'application/octet-stream')[:160]
    row.asset_type = str((record or {}).get('type') or row.asset_type or '')[:40]
    row.updated_date = datetime.utcnow()
    session.commit()


def load_asset_in_session(session: Any, asset_id: str) -> Optional[Dict[str, Any]]:
    """Return the blob, or a corrupt marker when the stored digest does not match."""
    from database.models import MediaLibraryBlob

    asset_id = str(asset_id or '').strip()
    if not asset_id:
        return None
    row = session.query(MediaLibraryBlob).filter_by(asset_id=asset_id).one_or_none()
    if row is None or row.payload is None:
        return None
    payload = bytes(row.payload)
    digest = hashlib.sha256(payload).hexdigest()
    recorded = str(row.sha256 or '').lower()
    if digest != recorded:
        logger.error('media_library_blobs checksum mismatch for %s', asset_id)
        return {
            'corrupt': True,
            'asset_id': asset_id,
            'sha256': recorded,
            'payload': b'',
            'record': {},
        }
    try:
        record = json.loads(row.record_json or '{}')
    except json.JSONDecodeError:
        record = {}
    if not isinstance(record, dict):
        record = {}
    return {
        'corrupt': False,
        'asset_id': asset_id,
        'sha256': digest,
        'payload': payload,
        'record': record,
    }


def delete_asset_in_session(session: Any, asset_id: str) -> bool:
    """Remove one blob. A missing row is already deleted."""
    from database.models import MediaLibraryBlob

    asset_id = str(asset_id or '').strip()
    if not asset_id:
        return False
    row = session.query(MediaLibraryBlob).filter_by(asset_id=asset_id).one_or_none()
    if row is not None:
        session.delete(row)
    session.commit()
    return True


def list_records_in_session(session: Any) -> List[Dict[str, Any]]:
    """Metadata only. Payloads stay in the database until a read needs them."""
    from database.models import MediaLibraryBlob

    rows = session.query(
        MediaLibraryBlob.asset_id,
        MediaLibraryBlob.sha256,
        MediaLibraryBlob.record_json,
    ).all()
    found: List[Dict[str, Any]] = []
    for asset_id, sha, raw in rows:
        try:
            record = json.loads(raw or '{}')
        except json.JSONDecodeError:
            record = {}
        if not isinstance(record, dict):
            record = {}
        found.append({
            'asset_id': str(asset_id or ''),
            'sha256': str(sha or '').lower(),
            'record': record,
        })
    return found


def _session_call(fn):
    from database import get_db_session

    session = get_db_session()
    try:
        return fn(session)
    except MediaLibraryIntegrityError:
        session.rollback()
        raise
    except MediaLibraryStoreError:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        logger.error('media library store failed: %s', type(exc).__name__)
        raise MediaLibraryStoreError('durable media store failed') from exc
    finally:
        session.close()


def seal_asset(asset_id: str, payload: bytes, record: Dict[str, Any]) -> str:
    return _session_call(lambda session: seal_asset_in_session(session, asset_id, payload, record))


def update_asset_record(asset_id: str, record: Dict[str, Any], expected_sha: str) -> None:
    return _session_call(lambda session: update_record_in_session(session, asset_id, record, expected_sha))


def load_asset(asset_id: str) -> Optional[Dict[str, Any]]:
    return _session_call(lambda session: load_asset_in_session(session, asset_id))


def delete_asset(asset_id: str) -> bool:
    return _session_call(lambda session: delete_asset_in_session(session, asset_id))


def list_asset_records() -> List[Dict[str, Any]]:
    return _session_call(list_records_in_session)
