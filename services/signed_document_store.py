"""Durable bytes for sealed signatures.

Mirrors the media-library rule: the SHA-256 of the payload is checked on
every read, an empty body is refused, and a different checksum is not written
over an existing row. Replacing bytes requires the caller to present the
digest currently stored (a verified promotion, not a silent overwrite).

The database table is the durable copy. Callers keep a file cache beside it.
With ``USE_DATABASE`` off, these functions are not used.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class SignedDocumentIntegrityError(Exception):
    """Bytes do not match the recorded checksum. Nothing was written."""


class SignedDocumentStoreError(Exception):
    """The durable store could not complete the write."""


def database_enabled() -> bool:
    return os.environ.get("USE_DATABASE", "").strip().lower() in ("1", "true", "yes", "on")


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def seal_in_session(session, asset_id: str, payload: bytes, asset_type: str = "signed_document") -> str:
    """Insert one payload. The same bytes are a no-op. Different bytes raise."""
    from database.models import SignedDocumentBlob

    asset_id = str(asset_id or "").strip()
    if not asset_id:
        raise SignedDocumentIntegrityError("signed document id is required")
    if not isinstance(payload, (bytes, bytearray)) or not payload:
        raise SignedDocumentIntegrityError("signed document payload is empty")
    payload = bytes(payload)
    digest = _digest(payload)
    row = session.query(SignedDocumentBlob).filter_by(asset_id=asset_id).one_or_none()
    if row is not None:
        recorded = str(row.sha256 or "").lower()
        if recorded != digest:
            raise SignedDocumentIntegrityError(
                "refusing to replace a sealed document with a different checksum"
            )
        return digest
    now = datetime.utcnow()
    session.add(SignedDocumentBlob(
        asset_id=asset_id,
        sha256=digest,
        size_bytes=len(payload),
        asset_type=str(asset_type or "signed_document")[:40],
        payload=payload,
        created_date=now,
        updated_date=now,
    ))
    session.commit()
    return digest


def replace_verified_in_session(session, asset_id: str, payload: bytes, expected_sha: str,
                                asset_type: str = "signed_document") -> str:
    """Replace bytes only when the stored digest is still ``expected_sha``."""
    from database.models import SignedDocumentBlob

    asset_id = str(asset_id or "").strip()
    expected_sha = str(expected_sha or "").strip().lower()
    if not asset_id or len(expected_sha) != 64:
        raise SignedDocumentIntegrityError("the current checksum is required to promote a sealed document")
    if not isinstance(payload, (bytes, bytearray)) or not payload:
        raise SignedDocumentIntegrityError("signed document payload is empty")
    payload = bytes(payload)
    digest = _digest(payload)
    row = session.query(SignedDocumentBlob).filter_by(asset_id=asset_id).one_or_none()
    if row is None:
        raise SignedDocumentStoreError("sealed document is missing")
    if str(row.sha256 or "").lower() != expected_sha:
        raise SignedDocumentIntegrityError("durable checksum does not match the sealed document")
    row.sha256 = digest
    row.size_bytes = len(payload)
    row.asset_type = str(asset_type or row.asset_type or "signed_document")[:40]
    row.payload = payload
    row.updated_date = datetime.utcnow()
    session.commit()
    return digest


def load_in_session(session, asset_id: str) -> Optional[bytes]:
    """Return the payload, or raise when the stored digest does not match."""
    from database.models import SignedDocumentBlob

    asset_id = str(asset_id or "").strip()
    if not asset_id:
        return None
    row = session.query(SignedDocumentBlob).filter_by(asset_id=asset_id).one_or_none()
    if row is None or row.payload is None:
        return None
    payload = bytes(row.payload)
    digest = _digest(payload)
    if digest != str(row.sha256 or "").lower():
        logger.error("signed_document_blobs checksum mismatch for %s", asset_id)
        raise SignedDocumentIntegrityError("sealed document checksum does not match")
    return payload


def _session_call(fn):
    from database import get_db_session

    session = get_db_session()
    try:
        return fn(session)
    except SignedDocumentIntegrityError:
        session.rollback()
        raise
    except SignedDocumentStoreError:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        logger.error("signed document store failed: %s", type(exc).__name__)
        raise SignedDocumentStoreError("durable signed-document store failed") from exc
    finally:
        session.close()


def seal(asset_id: str, payload: bytes, asset_type: str = "signed_document") -> str:
    return _session_call(lambda session: seal_in_session(session, asset_id, payload, asset_type))


def replace_verified(asset_id: str, payload: bytes, expected_sha: str,
                     asset_type: str = "signed_document") -> str:
    return _session_call(
        lambda session: replace_verified_in_session(session, asset_id, payload, expected_sha, asset_type)
    )


def load(asset_id: str) -> Optional[bytes]:
    return _session_call(lambda session: load_in_session(session, asset_id))
