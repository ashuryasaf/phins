"""Signed-document folder for NDAs accepted on an open link.

Each acceptance is written as its own file under
``PHINS_SIGNED_DOCUMENTS_DIR`` (default ``database/signed_documents/``),
created on the first signature. The file is the exact agreement text that
was hashed, the signer's name, the content digest and the platform-ledger
receipt. A checksum covers the file; a record whose text no longer hashes
to the signed digest, or whose checksum does not match, is not served.
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

        Refuses a text that does not hash to ``nda_sha256`` — the folder
        never keeps terms other than the ones that were signed.
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
        archive_id = _sha256(f"{instance}:{entry_id}")[:32]
        body = {
            "archive_id": archive_id,
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
            "nda_sha256": digest,
            "nda_text": text,
            "field_values": dict(record.get("field_values") or {}),
            "signature_method": str(record.get("signature_method") or "type")[:20],
            "signature_sha256": str(record.get("signature_sha256") or "")[:64],
            "use_mode": str(record.get("use_mode") or "")[:20],
            "stored_at": _utc_now_iso(),
        }
        sealed = dict(body)
        sealed["record_sha256"] = _sha256(_canonical(body))
        path = self._dir / f"{archive_id}.json"
        raw = json.dumps(sealed, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
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
        return archive_id

    def list_documents(self) -> List[Dict[str, Any]]:
        """Folder listing. A file that fails its seal is reported, not hidden."""
        items: List[Dict[str, Any]] = []
        if not self._dir.is_dir():
            return items
        for path in sorted(self._dir.glob("*.json")):
            try:
                record = self._read(path)
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
        path = self._dir / f"{clean}.json"
        if not path.is_file():
            raise ArchiveError("Signed document not found.")
        return self._read(path)

    def _read(self, path: Path) -> Dict[str, Any]:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArchiveError("Signed document could not be read.") from exc
        if not isinstance(record, dict):
            raise ArchiveError("Signed document is not a record.")
        seal = str(record.get("record_sha256") or "")
        body = {key: value for key, value in record.items() if key != "record_sha256"}
        if not seal or _sha256(_canonical(body)) != seal:
            raise ArchiveError("Signed document checksum does not match.")
        text = str(record.get("nda_text") or "")
        digest = str(record.get("nda_sha256") or "")
        if _sha256(text) != digest:
            raise ArchiveError("Signed NDA text does not match its digest.")
        record["intact"] = True
        return record

    @staticmethod
    def _summary(record: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "archive_id": record.get("archive_id"),
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
            "nda_sha256": record.get("nda_sha256"),
            "signature_method": record.get("signature_method"),
            "use_mode": record.get("use_mode"),
            "intact": True,
        }


def render_signed_html(record: Mapping[str, Any]) -> str:
    """Staff view of one sealed NDA: the terms that were signed, and the receipt."""
    def esc(value: Any) -> str:
        return (str(value if value is not None else "")
                .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;"))

    rtl = str(record.get("lang") or "") == "he"
    text = esc(record.get("nda_text")).replace("\n", "<br>\n")
    return f"""<!DOCTYPE html>
<html lang="{esc(record.get('lang') or 'en')}" {'dir="rtl"' if rtl else ''}>
<head><meta charset="utf-8"><title>Signed NDA · {esc(record.get('signer_name'))}</title>
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
  <h1>Signed NDA · {esc(record.get('label'))}</h1>
  <p class="meta">{esc(record.get('signer_name'))} · {esc(record.get('role'))} · {esc(record.get('signed_at'))}<br>
  {esc(record.get('doc_instance_id'))} · ledger #{esc(record.get('sequence_no'))} · {esc(record.get('entry_id'))}<br>
  SHA-256 <code>{esc(record.get('nda_sha256'))}</code></p>
</header>
<div class="terms">{text}</div>
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
