"""Durable media-dashboard design document.

The ledger JSON file lives on container disk and disappears on a new deploy.
Placement choices (which video is the login hero, which image is the
background or thumbnail) are stored here as one checksummed row so a restart
reloads the same document the dashboard saved.

The canonical payload is compact JSON with sorted keys. ``sha256`` is the
digest of those exact bytes. A row whose bytes do not match the stored
digest is corrupt and is not returned as a usable document. A write that
loses the revision race raises ``MediaDesignConflict`` and does not replace
the newer row.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DESIGN_DOCUMENT_ID = 'current'


class MediaDesignIntegrityError(Exception):
    """The document bytes do not match the recorded checksum. Nothing was applied."""


class MediaDesignStoreError(Exception):
    """The durable store could not complete the read or write."""


class MediaDesignConflict(Exception):
    """Another writer committed a newer revision. The stored document is intact."""

    def __init__(self, revision: int, payload: Dict[str, Any]):
        super().__init__('design document revision conflict')
        self.revision = int(revision or 0)
        self.payload = payload if isinstance(payload, dict) else {}


def canonical_bytes(payload: Dict[str, Any]) -> bytes:
    """Stable UTF-8 JSON for the checksum. Key order cannot change the digest."""
    if not isinstance(payload, dict):
        raise MediaDesignIntegrityError('design document must be an object')
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=True,
        default=str,
    ).encode('utf-8')


def document_checksum(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def merge_design_documents(
    stored: Dict[str, Any],
    base: Optional[Dict[str, Any]],
    incoming: Dict[str, Any],
) -> Dict[str, Any]:
    """Keep the stored document, then overlay keys the caller changed since ``base``.

    A replica that saved a login hero must not lose that slot when another
    replica, still holding an older copy, saves a background. Keys the caller
    did not change stay as the stored row left them.
    """
    merged = copy.deepcopy(stored if isinstance(stored, dict) else {})
    if not isinstance(incoming, dict):
        raise MediaDesignIntegrityError('design document must be an object')
    if not isinstance(base, dict):
        return copy.deepcopy(incoming)
    for key, value in incoming.items():
        if base.get(key) != value:
            merged[key] = copy.deepcopy(value)
    return merged


def _payload_from_row(raw: str, recorded: str) -> Dict[str, Any]:
    body = raw if isinstance(raw, str) else ''
    digest = hashlib.sha256(body.encode('utf-8')).hexdigest()
    recorded = str(recorded or '').strip().lower()
    if not recorded or digest != recorded:
        raise MediaDesignIntegrityError('design document checksum mismatch')
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise MediaDesignIntegrityError('design document is not valid JSON') from exc
    if not isinstance(payload, dict):
        raise MediaDesignIntegrityError('design document must be an object')
    return payload


def _conflict_for_stored_row(session: Any) -> Exception:
    """Read the committed row and describe the race the caller lost."""
    from database.models import MediaDesignDocument

    raced = session.query(MediaDesignDocument).filter_by(id=DESIGN_DOCUMENT_ID).one_or_none()
    if raced is None:
        return MediaDesignStoreError('durable design write failed')
    return MediaDesignConflict(
        int(raced.revision or 0),
        _payload_from_row(raced.payload_json or '', raced.sha256 or ''),
    )


def seal_design_in_session(
    session: Any,
    payload: Dict[str, Any],
    expected_revision: Optional[int] = None,
) -> Dict[str, Any]:
    """Insert or replace the singleton. Raises on a revision race or a bad read-back."""
    from sqlalchemy.exc import IntegrityError

    from database.models import MediaDesignDocument

    encoded = canonical_bytes(payload)
    digest = hashlib.sha256(encoded).hexdigest()
    text = encoded.decode('utf-8')
    row = session.query(MediaDesignDocument).filter_by(id=DESIGN_DOCUMENT_ID).one_or_none()
    now = datetime.utcnow()
    if row is None:
        if expected_revision not in (None, 0):
            raise MediaDesignConflict(0, {})
        row = MediaDesignDocument(
            id=DESIGN_DOCUMENT_ID,
            sha256=digest,
            revision=1,
            payload_json=text,
            created_date=now,
            updated_date=now,
        )
        session.add(row)
    else:
        current = int(row.revision or 0)
        if expected_revision is None or int(expected_revision) != current:
            try:
                current_payload = _payload_from_row(row.payload_json or '', row.sha256 or '')
            except MediaDesignIntegrityError:
                session.rollback()
                raise
            raise MediaDesignConflict(current, current_payload)
        # Compare-and-swap on the revision the caller read. A replica that
        # committed between that read and this update keeps its row: the
        # condition no longer matches and nothing is replaced.
        changed = session.query(MediaDesignDocument).filter(
            MediaDesignDocument.id == DESIGN_DOCUMENT_ID,
            MediaDesignDocument.revision == current,
        ).update(
            {
                'sha256': digest,
                'revision': current + 1,
                'payload_json': text,
                'updated_date': now,
            },
            synchronize_session=False,
        )
        if changed != 1:
            session.rollback()
            raise _conflict_for_stored_row(session)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise _conflict_for_stored_row(session) from exc

    session.expire_all()
    check = session.query(MediaDesignDocument).filter_by(id=DESIGN_DOCUMENT_ID).one_or_none()
    if check is None:
        raise MediaDesignStoreError('durable design document missing after write')
    try:
        verified = _payload_from_row(check.payload_json or '', check.sha256 or '')
    except MediaDesignIntegrityError:
        session.rollback()
        raise
    if str(check.sha256 or '').lower() != digest:
        raise MediaDesignIntegrityError('design document checksum mismatch after write')
    if canonical_bytes(verified) != encoded:
        raise MediaDesignIntegrityError('design document changed during write')
    return {
        'revision': int(check.revision or 0),
        'sha256': digest,
        'payload': verified,
    }


def load_design_in_session(session: Any) -> Optional[Dict[str, Any]]:
    """Return the document, or a corrupt marker. Missing is ``None``."""
    from database.models import MediaDesignDocument

    row = session.query(MediaDesignDocument).filter_by(id=DESIGN_DOCUMENT_ID).one_or_none()
    if row is None:
        return None
    try:
        payload = _payload_from_row(row.payload_json or '', row.sha256 or '')
    except MediaDesignIntegrityError:
        logger.error('media_design_documents checksum mismatch')
        return {
            'corrupt': True,
            'revision': int(row.revision or 0),
            'sha256': str(row.sha256 or '').lower(),
            'payload': {},
        }
    return {
        'corrupt': False,
        'revision': int(row.revision or 0),
        'sha256': str(row.sha256 or '').lower(),
        'payload': payload,
    }


def _session_call(fn):
    from database import get_db_session

    session = get_db_session()
    try:
        return fn(session)
    except MediaDesignIntegrityError:
        session.rollback()
        raise
    except MediaDesignConflict:
        session.rollback()
        raise
    except MediaDesignStoreError:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        logger.error('media design store failed: %s', type(exc).__name__)
        raise MediaDesignStoreError('durable design store failed') from exc
    finally:
        session.close()


def seal_design(payload: Dict[str, Any], expected_revision: Optional[int] = None) -> Dict[str, Any]:
    return _session_call(
        lambda session: seal_design_in_session(session, payload, expected_revision)
    )


def load_design() -> Optional[Dict[str, Any]]:
    return _session_call(load_design_in_session)
