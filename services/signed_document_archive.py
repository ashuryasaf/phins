"""Sealed copy of every signed document.

Open-link NDAs keep the exact agreement text that was hashed. Any other
anchored signature keeps the content snapshot and the attested digest.
Each file is checksummed. When the database is on, the same bytes are
sealed first (media-library rule: checked on read, never silently
replaced). A record whose text no longer hashes to the signed digest, or
whose checksum does not match, is not served.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

__all__ = [
    "ArchiveError",
    "SignedDocumentArchive",
    "get_signed_document_archive",
    "reset_signed_document_archive_for_tests",
]

_ENV_DIR = "PHINS_SIGNED_DOCUMENTS_DIR"
_DEFAULT_DIR = "signed_documents"


class ArchiveError(ValueError):
    """The signed document could not be stored or no longer matches its seal."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _archive_id(instance: str, entry_id: str) -> str:
    return _sha256(f"{instance}:{entry_id}")[:32]


def _encode(sealed: Mapping[str, Any]) -> bytes:
    return (json.dumps(sealed, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


class SignedDocumentArchive:
    def __init__(self, data_dir: Optional[str] = None):
        if data_dir:
            self._dir = Path(data_dir)
        else:
            env = os.environ.get(_ENV_DIR, "").strip()
            if env:
                self._dir = Path(env)
            else:
                self._dir = Path(__file__).resolve().parent.parent / "database" / _DEFAULT_DIR
        self._lock = threading.RLock()

    @property
    def directory(self) -> Path:
        return self._dir

    def store(self, record: Mapping[str, Any]) -> str:
        """Seal one signed NDA and return its archive id.

        Refuses a text that does not hash to ``nda_sha256``. The same
        ledger entry is stored once. An earlier attestation of that entry
        may be promoted to the full text when the digest matches. A
        different text, or a file whose seal is already broken, is refused.
        """
        text = str(record.get("nda_text") or "")
        digest = str(record.get("nda_sha256") or "").strip().lower()
        if not text or len(digest) != 64:
            raise ArchiveError("A signed NDA needs its text and sha256 digest.")
        if _sha256(text) != digest:
            raise ArchiveError("NDA text does not match the signed digest.")
        instance = str(record.get("doc_instance_id") or "").strip()
        entry_id = str(record.get("entry_id") or "").strip()
        if not instance or not entry_id:
            raise ArchiveError("A signed NDA needs its document instance and ledger entry.")
        archive_id = _archive_id(instance, entry_id)
        body = {
            "archive_id": archive_id,
            "kind": "nda",
            "doc_type": str(record.get("doc_type") or "nda")[:80],
            "doc_instance_id": instance[:120],
            "entry_id": entry_id[:160],
            "entry_hash": str(record.get("entry_hash") or "")[:128],
            "sequence_no": record.get("sequence_no"),
            "share_id": str(record.get("share_id") or "")[:80],
            "label": str(record.get("label") or "")[:120],
            "signer_name": str(record.get("signer_name") or "")[:120],
            "role": str(record.get("role") or "Receiving Party")[:80],
            "signed_at": str(record.get("signed_at") or _utc_now_iso())[:40],
            "lang": str(record.get("lang") or "en")[:8],
            "nda_version": str(record.get("nda_version") or "")[:80],
            "document_hash": digest,
            "nda_sha256": digest,
            "nda_text": text,
            "field_values": dict(record.get("field_values") or {}),
            "signature_method": str(record.get("signature_method") or "type")[:20],
            "signature_sha256": str(record.get("signature_sha256") or "")[:64],
            "use_mode": str(record.get("use_mode") or "")[:20],
            "stored_at": _utc_now_iso(),
        }
        with self._lock:
            existing, previous_sha = self._existing(archive_id)
            if existing is not None:
                self._refuse_conflict(existing, entry_id, digest)
                if str(existing.get("nda_text") or "") == text:
                    return archive_id
                if str(existing.get("nda_text") or ""):
                    raise ArchiveError("Signed document checksum does not match.")
                # Attestation promoted to the full text. stored_at stays the
                # original seal time so the promotion is the only change
                # besides the text that was already hashed.
                body["stored_at"] = existing.get("stored_at") or body["stored_at"]
            archive_id = self._commit(archive_id, body, previous_sha=previous_sha if existing else None)
        self._note_signed(body)
        return archive_id

    def store_signature(self, record: Mapping[str, Any]) -> str:
        """Seal any anchored signature, even when the full text is elsewhere.

        ``document_text``, when present, must hash to ``document_hash``.
        A later ``store`` of the NDA text for the same ledger entry promotes
        this attestation. A different digest is refused.
        """
        digest = str(record.get("document_hash") or record.get("nda_sha256") or "").strip().lower()
        text = str(record.get("document_text") or record.get("nda_text") or "")
        if len(digest) != 64:
            raise ArchiveError("A signed document needs its sha256 digest.")
        if text and _sha256(text) != digest:
            raise ArchiveError("Signed text does not match the attested digest.")
        instance = str(record.get("doc_instance_id") or "").strip()
        entry_id = str(record.get("entry_id") or "").strip()
        if not instance or not entry_id:
            raise ArchiveError("A signed document needs its document instance and ledger entry.")
        content = record.get("content")
        if content is not None and not isinstance(content, dict):
            content = None
        archive_id = _archive_id(instance, entry_id)
        body = {
            "archive_id": archive_id,
            "kind": "signature",
            "doc_type": str(record.get("doc_type") or "")[:80],
            "doc_instance_id": instance[:120],
            "entry_id": entry_id[:160],
            "entry_hash": str(record.get("entry_hash") or "")[:128],
            "sequence_no": record.get("sequence_no"),
            "share_id": str(record.get("share_id") or "")[:80],
            "label": str(record.get("label") or "")[:120],
            "signer_name": str(record.get("signer_name") or "")[:120],
            "role": str(record.get("role") or "")[:80],
            "signed_at": str(record.get("signed_at") or _utc_now_iso())[:40],
            "lang": str(record.get("lang") or "en")[:8],
            "document_hash": digest,
            "document_text": text,
            "content": content or {},
            "signature_method": str(record.get("signature_method") or "")[:20],
            "stored_at": _utc_now_iso(),
        }
        with self._lock:
            existing, previous_sha = self._existing(archive_id)
            if existing is not None:
                self._refuse_conflict(existing, entry_id, digest)
                return archive_id
            self._commit(archive_id, body, previous_sha=previous_sha)
        self._note_signed(body)
        return archive_id

    def _commit(self, archive_id: str, body: Dict[str, Any], previous_sha: Optional[str]) -> str:
        sealed = dict(body)
        sealed["record_sha256"] = _sha256(_canonical(body))
        raw = _encode(sealed)
        digest = hashlib.sha256(raw).hexdigest()
        from services import signed_document_store as durable
        if durable.database_enabled():
            if previous_sha:
                durable.replace_verified(archive_id, raw, previous_sha, "signed_document")
            else:
                durable.seal(archive_id, raw, "signed_document")
        self._write_file(archive_id, raw)
        return archive_id

    def _write_file(self, archive_id: str, raw: bytes) -> None:
        path = self._dir / f"{archive_id}.json"
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(str(tmp), str(path))
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def _existing(self, archive_id: str):
        """Return ``(record, sha256 of the sealed bytes)`` or ``(None, None)``."""
        raw = self._durable_bytes(archive_id)
        path = self._dir / f"{archive_id}.json"
        if raw is None and path.is_file():
            raw = path.read_bytes()
        if not raw:
            return None, None
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArchiveError("Signed document checksum does not match.") from exc
        self._validate(record)
        return record, hashlib.sha256(raw).hexdigest()

    def _durable_bytes(self, archive_id: str) -> Optional[bytes]:
        from services import signed_document_store as durable
        if not durable.database_enabled():
            return None
        try:
            return durable.load(archive_id)
        except durable.SignedDocumentIntegrityError as exc:
            raise ArchiveError("Signed document checksum does not match.") from exc

    @staticmethod
    def _refuse_conflict(existing: Mapping[str, Any], entry_id: str, digest: str) -> None:
        attested = str(existing.get("document_hash") or existing.get("nda_sha256") or "").lower()
        if str(existing.get("entry_id") or "") != entry_id or attested != digest:
            raise ArchiveError("Signed document checksum does not match.")

    def _note_signed(self, body: Mapping[str, Any]) -> None:
        try:
            from services.document_use_ledger import get_document_use_ledger
            name = str(body.get("label") or body.get("doc_type") or "Signed document")
            get_document_use_ledger().record(
                action="signed",
                idempotency_key=f"signed:{body.get('entry_id')}",
                document_name=name,
                document_path="",
                doc_instance_id=body.get("doc_instance_id") or "",
                archive_id=body.get("archive_id") or "",
                share_id=body.get("share_id") or "",
                actor=body.get("signer_name") or "",
                content_sha256=body.get("document_hash") or body.get("nda_sha256") or "",
                entry_id=body.get("entry_id") or "",
                at=body.get("signed_at") or "",
            )
        except Exception as exc:
            print(f"⚠️  [SIGNED] use ledger did not record the signature: {exc}")

    def list_documents(self) -> List[Dict[str, Any]]:
        """Folder listing. A file that fails its seal is reported, not hidden."""
        items: List[Dict[str, Any]] = []
        if not self._dir.is_dir():
            return items
        for path in sorted(self._dir.glob("*.json")):
            try:
                record = self.get(path.stem)
            except ArchiveError as exc:
                items.append({
                    "archive_id": path.stem,
                    "intact": False,
                    "error": str(exc),
                })
                continue
            items.append(self._summary(record))
        items.sort(key=lambda item: str(item.get("signed_at") or ""), reverse=True)
        return items

    def get(self, archive_id: str) -> Dict[str, Any]:
        clean = "".join(ch for ch in str(archive_id or "") if ch.isalnum())
        if len(clean) < 16:
            raise ArchiveError("Signed document not found.")
        raw = self._durable_bytes(clean)
        path = self._dir / f"{clean}.json"
        if raw is None:
            if not path.is_file():
                raise ArchiveError("Signed document not found.")
            return self._read(path)
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArchiveError("Signed document could not be read.") from exc
        self._validate(record)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != hashlib.sha256(raw).hexdigest():
            try:
                self._write_file(clean, raw)
            except OSError:
                pass
        record["intact"] = True
        return record

    def _read(self, path: Path) -> Dict[str, Any]:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArchiveError("Signed document could not be read.") from exc
        self._validate(record)
        record["intact"] = True
        return record

    @staticmethod
    def _validate(record: Any) -> None:
        if not isinstance(record, dict):
            raise ArchiveError("Signed document is not a record.")
        seal = str(record.get("record_sha256") or "")
        body = {key: value for key, value in record.items() if key != "record_sha256"}
        if not seal or _sha256(_canonical(body)) != seal:
            raise ArchiveError("Signed document checksum does not match.")
        text = str(record.get("nda_text") or record.get("document_text") or "")
        digest = str(record.get("nda_sha256") or record.get("document_hash") or "")
        if text:
            if _sha256(text) != digest:
                raise ArchiveError("Signed text does not match its digest.")
        elif len(digest) != 64:
            raise ArchiveError("Signed document is missing its digest.")

    @staticmethod
    def _summary(record: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "archive_id": record.get("archive_id"),
            "kind": record.get("kind") or "nda",
            "doc_type": record.get("doc_type") or "nda",
            "doc_instance_id": record.get("doc_instance_id"),
            "entry_id": record.get("entry_id"),
            "sequence_no": record.get("sequence_no"),
            "share_id": record.get("share_id"),
            "label": record.get("label"),
            "signer_name": record.get("signer_name"),
            "role": record.get("role"),
            "signed_at": record.get("signed_at"),
            "lang": record.get("lang"),
            "nda_version": record.get("nda_version"),
            "nda_sha256": record.get("nda_sha256") or record.get("document_hash"),
            "document_hash": record.get("document_hash") or record.get("nda_sha256"),
            "signature_method": record.get("signature_method"),
            "use_mode": record.get("use_mode"),
            "intact": True,
        }


def render_signed_html(record: Mapping[str, Any]) -> str:
    """Staff view of one sealed signature. Capture is blocked on this page."""
    def esc(value: Any) -> str:
        return (str(value if value is not None else "")
                .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;"))

    rtl = str(record.get("lang") or "") == "he"
    text = str(record.get("nda_text") or record.get("document_text") or "")
    if not text and record.get("content"):
        text = json.dumps(record.get("content"), indent=2, sort_keys=True, ensure_ascii=False)
    body = esc(text).replace("\n", "<br>\n")
    digest = record.get("nda_sha256") or record.get("document_hash")
    title = record.get("label") or record.get("doc_type") or "Signed document"
    try:
        from services.document_capture_guard import markup
        guard = markup(
            " · ".join(part for part in (
                str(record.get("signer_name") or ""),
                str(title),
                str(record.get("signed_at") or ""),
            ) if part),
            inline=True,
        )
    except Exception:
        guard = ""
    return f"""<!DOCTYPE html>
<html lang="{esc(record.get('lang') or 'en')}" {'dir="rtl"' if rtl else ''}>
<head><meta charset="utf-8"><title>Signed document · {esc(record.get('signer_name'))}</title>
<style>
body {{ font: 15px/1.5 Georgia, serif; margin: 32px auto; max-width: 760px; color: #172033; }}
header {{ font-family: Inter, sans-serif; border-bottom: 3px solid #c9a04e; padding-bottom: 12px; margin-bottom: 18px; }}
h1 {{ font-size: 22px; margin: 0 0 4px; }}
.meta {{ font-size: 13px; color: #4a5670; }}
code {{ font-size: 12px; }}
.terms {{ white-space: normal; }}
</style></head>
<body>
<header>
  <h1>Signed document · {esc(title)}</h1>
  <p class="meta">{esc(record.get('signer_name'))} · {esc(record.get('role'))} · {esc(record.get('signed_at'))}<br>
  {esc(record.get('doc_instance_id'))} · ledger #{esc(record.get('sequence_no'))} · {esc(record.get('entry_id'))}<br>
  SHA-256 <code>{esc(digest)}</code></p>
</header>
<div class="terms">{body}</div>
{guard}
</body></html>
"""


_archive: Optional[SignedDocumentArchive] = None
_archive_lock = threading.Lock()


def get_signed_document_archive(data_dir: Optional[str] = None) -> SignedDocumentArchive:
    global _archive
    with _archive_lock:
        if _archive is None or data_dir is not None:
            _archive = SignedDocumentArchive(data_dir)
        return _archive


def reset_signed_document_archive_for_tests() -> None:
    global _archive
    with _archive_lock:
        _archive = None
