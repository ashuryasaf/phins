"""Admin durability test for the document pipeline.

The agent does two things, and neither one rewrites a customer file:

* It reads the platform archive and counts, by process and media type, how
  many uploads are still stored. A missing file or a checksum mismatch is
  reported. It is not repaired here.
* It seals one fixed text probe through the same upload path the platform
  uses (data-URL stripped, SHA-256 of the bytes, disk write, read-back),
  then deletes that probe. A fingerprint of every other document is taken
  before the probe and checked after it is gone.

The probe lives in the reserved ``durability_probe`` lane. That lane is
excluded from the customer vault and the platform archive.
"""

from __future__ import annotations

import base64
import hashlib
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from services.customer_document_vault_service import (
    DURABILITY_PROBE_ENTITY,
    decode_document_bytes,
    fingerprint_upload,
)

AGENT_ID = "document_durability"
LAUNCH_DATE = "2025-12-01"
PROBE_NAME = "phins-durability-probe.txt"
PROBE_TEXT = b"PHINS internal durability probe. Not a customer document.\n"
PROBE_SHA256 = hashlib.sha256(PROBE_TEXT).hexdigest()
MEDIA_KINDS = ("document", "voice", "video", "image")
MAX_ARCHIVE_SCAN = 10000
_PAGE_SIZE = 200

PROCESS_LABELS = {
    "claims": "Claims",
    "claims_chat": "Claims chat",
    "underwriting": "Underwriting applications",
    "apply_chat": "Apply chat",
    "policy_documents": "Policy documents",
    "billing": "Billing",
    "receipt": "Receipts",
    "identity": "Identity",
    "medical": "Medical",
    "risk_assessment": "Risk assessment",
    "authority": "Authority",
    "general": "General",
}


def media_kind(record: Dict[str, Any]) -> str:
    """Classify a vault row as document, voice, video, or image."""
    mime = str(record.get("type") or record.get("mime_type") or "").strip().lower()
    name = str(record.get("name") or record.get("original_file_name") or "").strip().lower()
    kind = str(record.get("kind") or "").strip().lower()
    if mime.startswith("audio/") or kind in {"voice", "audio"} or _endswith(
        name, (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".wma")
    ):
        return "voice"
    if mime.startswith("video/") or kind == "video" or _endswith(
        name, (".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv")
    ):
        return "video"
    if mime.startswith("image/") or kind == "image" or _endswith(
        name, (".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff", ".bmp", ".svg")
    ):
        return "image"
    return "document"


def process_bucket(record: Dict[str, Any]) -> str:
    """Group a row by the pipeline that accepted it."""
    entity = str(record.get("entity_type") or "").strip().lower()
    if entity in {"claim", "claims"}:
        return "claims"
    if entity == "claims_chat":
        return "claims_chat"
    if entity in {"underwriting", "application"}:
        return "underwriting"
    if entity == "chat_application":
        return "apply_chat"
    if entity in {"policy", "policies"}:
        return "policy_documents"
    if entity == "billing":
        return "billing"
    tag = str(record.get("process_hashtag") or "").strip().lower()
    if tag in PROCESS_LABELS:
        return tag
    if tag:
        return tag
    return "general"


def is_stored(record: Dict[str, Any]) -> bool:
    """True when the bytes are still on hand and the checksum was not rejected."""
    status = str(record.get("integrity_status") or "unverified").strip().lower()
    if status in {"missing", "mismatch"}:
        return False
    if status == "ok":
        return True
    return bool(record.get("has_data"))


def build_census(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Count uploads and still-stored bytes. Does not read or write files."""
    buckets: Dict[str, Dict[str, Any]] = {}
    integrity = {"ok": 0, "mismatch": 0, "missing": 0, "unverified": 0}
    issues: List[Dict[str, Any]] = []

    for record in records:
        if not isinstance(record, dict):
            continue
        if str(record.get("entity_type") or "").strip().lower() == DURABILITY_PROBE_ENTITY:
            continue
        if str(record.get("document_type") or "").strip().lower() == DURABILITY_PROBE_ENTITY:
            continue
        process = process_bucket(record)
        media = media_kind(record)
        row = buckets.setdefault(process, _empty_row(process))
        row["uploaded"] += 1
        row["by_media"][media] += 1
        status = str(record.get("integrity_status") or "unverified").strip().lower()
        if status not in integrity:
            status = "unverified"
        integrity[status] += 1
        if is_stored(record):
            row["stored"] += 1
            row["stored_by_media"][media] += 1
        elif status in {"missing", "mismatch"} and len(issues) < 40:
            issues.append({
                "id": str(record.get("id") or ""),
                "name": str(record.get("name") or ""),
                "process": process,
                "media": media,
                "integrity_status": status,
            })

    rows = [_finalize_row(row) for row in buckets.values()]
    rows.sort(key=lambda item: (-item["uploaded"], item["process"]))
    return {
        "rows": rows,
        "totals": _totals(rows),
        "integrity": integrity,
        "issues": issues,
        "archive_consistent": integrity["mismatch"] == 0 and integrity["missing"] == 0,
    }


def run_pipeline_probe(
    doc_service: Any,
    *,
    actor: str = "admin",
    sibling_before: Optional[Dict[str, Tuple]] = None,
) -> Dict[str, Any]:
    """Seal one probe file and delete it. Customer rows are only compared."""
    steps: List[Dict[str, Any]] = []
    probe_id = ""
    storage_path = ""
    siblings_checked = 0
    changed_id = ""
    removed = False

    wrapped = "data:text/plain;base64," + base64.b64encode(PROBE_TEXT).decode("ascii")
    raw = decode_document_bytes(wrapped)
    wrapper_ok = raw == PROBE_TEXT
    steps.append(_step(
        "wrapper_stripped",
        wrapper_ok,
        "Data-URL prefix removed before hashing" if wrapper_ok else "Data-URL decode did not match the probe bytes",
    ))
    digest = fingerprint_upload(wrapped)
    fingerprint_ok = wrapper_ok and digest == PROBE_SHA256
    steps.append(_step(
        "fingerprint",
        fingerprint_ok,
        "SHA-256 is of the file bytes" if fingerprint_ok else "Fingerprint did not match the probe bytes",
    ))

    if sibling_before is None:
        sibling_before, _total = _fingerprint_store(doc_service)
    siblings_checked = len(sibling_before)

    try:
        if not fingerprint_ok:
            raise RuntimeError("probe bytes failed the fingerprint check")
        uploaded = doc_service.upload_document(
            file_name=PROBE_NAME,
            file_data_b64=base64.b64encode(PROBE_TEXT).decode("ascii"),
            mime_type="text/plain",
            category="general",
            document_type=DURABILITY_PROBE_ENTITY,
            description="Internal durability probe. Not a customer document.",
            entity_type=DURABILITY_PROBE_ENTITY,
            entity_id=f"PROBE-{uuid.uuid4().hex[:12]}",
            customer_id="",
            uploaded_by=actor or "admin",
            uploaded_by_role="admin",
            skip_processing=True,
        )
        probe_id = str(getattr(uploaded, "document_id", "") or "")
        storage_path = str(getattr(uploaded, "storage_path", "") or "")
        sealed_sha = str(getattr(uploaded, "sha256", "") or "")
        sealed_ok = bool(probe_id) and sealed_sha == PROBE_SHA256 and getattr(uploaded, "status", "") != "integrity_error"
        steps.append(_step(
            "sealed",
            sealed_ok,
            "Probe stored under the reserved lane" if sealed_ok else "Upload did not seal the probe checksum",
        ))

        checked = doc_service.verify_integrity(probe_id) if probe_id else {"valid": False}
        disk_ok = bool(checked.get("valid")) and checked.get("actual_sha256") == PROBE_SHA256
        steps.append(_step(
            "disk_matches",
            disk_ok,
            "On-disk bytes match the sealed SHA-256" if disk_ok else "On-disk checksum did not match",
        ))

        loaded = doc_service.get_document(probe_id, include_data=True) if probe_id else None
        readback = b""
        if isinstance(loaded, dict) and loaded.get("data"):
            try:
                readback = base64.b64decode(loaded["data"], validate=True)
            except Exception:
                readback = b""
        read_ok = (
            isinstance(loaded, dict)
            and loaded.get("sha256_checksum") == PROBE_SHA256
            and readback == PROBE_TEXT
            and str(loaded.get("customer_id") or "") == ""
            and str(loaded.get("entity_type") or "") == DURABILITY_PROBE_ENTITY
        )
        steps.append(_step(
            "readback",
            read_ok,
            "Read-back bytes match the probe and carry no customer id" if read_ok else "Read-back did not match the sealed probe",
        ))
    except Exception as exc:
        if not any(step["id"] == "sealed" for step in steps):
            steps.append(_step("sealed", False, str(exc)))
        else:
            steps.append(_step("probe_error", False, str(exc)))
    finally:
        removed = _remove_probe(doc_service, probe_id, storage_path) if probe_id else not storage_path
        steps.append(_step(
            "removed",
            removed,
            "Probe file and record deleted" if removed else "Probe could not be removed",
        ))

    after, _after_total = _fingerprint_store(doc_service)
    intact, changed_id = _siblings_intact(sibling_before, after, probe_id)
    steps.append(_step(
        "siblings_unchanged",
        intact,
        f"{siblings_checked} other document(s) unchanged"
        if intact else f"Another document changed: {changed_id}",
    ))

    passed = all(step["passed"] for step in steps)
    return {
        "passed": passed,
        "probe_sha256": PROBE_SHA256,
        "probe_document_id": None if removed else (probe_id or None),
        "probe_removed": removed,
        "siblings_checked": siblings_checked,
        "siblings_unchanged": intact,
        "steps": steps,
    }


def run_durability_test(
    *,
    vault: Any,
    doc_service: Any,
    actor: str = "admin",
) -> Dict[str, Any]:
    """Read the archive, then run the isolated probe. Customer bytes stay put."""
    reaped = reap_own_probes(doc_service)
    sibling_before, _total = _fingerprint_store(doc_service)
    scanned, truncated = _archive_records(vault)
    since, undated, _before = _split_launch(scanned)
    census = {
        "launch_date": LAUNCH_DATE,
        "census_complete": not truncated,
        "scanned": len(scanned),
        "since_launch": build_census(since),
        "undated": build_census(undated),
        "all_time": build_census(scanned),
    }
    pipeline = run_pipeline_probe(
        doc_service,
        actor=actor,
        sibling_before=sibling_before,
    )
    archive_consistent = (
        census["since_launch"]["archive_consistent"]
        and census["all_time"]["archive_consistent"]
        and census["undated"]["archive_consistent"]
        and not truncated
        and not reaped["foreign"]
    )
    passed = bool(pipeline["passed"]) and archive_consistent
    return {
        "success": True,
        "agent_id": AGENT_ID,
        "passed": passed,
        "archive_consistent": archive_consistent,
        "writes_customer_documents": False,
        "launch_date": LAUNCH_DATE,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "actor": actor,
        "reaped_prior_probes": reaped["reaped"],
        "foreign_probe_ids": reaped["foreign"],
        "census": census,
        "pipeline": pipeline,
    }


def reap_own_probes(doc_service: Any) -> Dict[str, List[str]]:
    """Delete leftover probes whose checksum is the known probe. Leave anything else."""
    reaped: List[str] = []
    foreign: List[str] = []
    page = 1
    while page <= 20:
        listing = doc_service.list_documents(
            entity_type=DURABILITY_PROBE_ENTITY,
            page=page,
            page_size=_PAGE_SIZE,
        )
        items = (listing or {}).get("items") or []
        if not items:
            break
        for item in items:
            if not isinstance(item, dict):
                continue
            doc_id = str(item.get("id") or "")
            digest = str(item.get("sha256_checksum") or "")
            entity = str(item.get("entity_type") or "")
            if entity == DURABILITY_PROBE_ENTITY and digest == PROBE_SHA256 and doc_id:
                if _remove_probe(doc_service, doc_id, str(item.get("storage_path") or "")):
                    reaped.append(doc_id)
                else:
                    foreign.append(doc_id)
            elif doc_id:
                foreign.append(doc_id)
        if len(items) < _PAGE_SIZE:
            break
        page += 1
    return {"reaped": reaped, "foreign": foreign}


def _archive_records(vault: Any) -> Tuple[List[Dict[str, Any]], bool]:
    records: List[Dict[str, Any]] = []
    offset = 0
    truncated = False
    while offset < MAX_ARCHIVE_SCAN:
        payload = vault.get_platform_archive(
            limit=_PAGE_SIZE,
            offset=offset,
            verify_integrity=True,
            viewer_role="admin",
        )
        batch = list((payload or {}).get("documents") or [])
        total = int((payload or {}).get("total") or 0)
        records.extend(batch)
        offset += len(batch)
        if not batch or offset >= total:
            return records, False
    return records, True


def _split_launch(
    records: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    since: List[Dict[str, Any]] = []
    undated: List[Dict[str, Any]] = []
    before: List[Dict[str, Any]] = []
    for record in records:
        stamp = _timestamp(record.get("uploaded_at"))
        if not stamp:
            undated.append(record)
        elif stamp >= LAUNCH_DATE:
            since.append(record)
        else:
            before.append(record)
    return since, undated, before


def _fingerprint_store(doc_service: Any) -> Tuple[Dict[str, Tuple], int]:
    seen: Dict[str, Tuple] = {}
    total = 0
    page = 1
    while page <= 50:
        listing = doc_service.list_documents(page=page, page_size=_PAGE_SIZE)
        items = (listing or {}).get("items") or []
        total = int((listing or {}).get("total") or 0)
        for item in items:
            if not isinstance(item, dict):
                continue
            doc_id = str(item.get("id") or "")
            if not doc_id:
                continue
            seen[doc_id] = (
                str(item.get("sha256_checksum") or ""),
                int(item.get("file_size") or 0),
                str(item.get("status") or ""),
                str(item.get("storage_path") or ""),
                str(item.get("entity_type") or ""),
            )
        if not items or len(seen) >= total:
            break
        page += 1
    return seen, total


def _siblings_intact(
    before: Dict[str, Tuple],
    after: Dict[str, Tuple],
    probe_id: str,
) -> Tuple[bool, str]:
    for doc_id, fingerprint in before.items():
        if after.get(doc_id) != fingerprint:
            return False, doc_id
    for doc_id in after:
        if doc_id not in before and doc_id != probe_id:
            return False, doc_id
    if probe_id and probe_id in after:
        return False, probe_id
    return True, ""


def _remove_probe(doc_service: Any, doc_id: str, storage_path: str) -> bool:
    if not doc_id:
        return not storage_path
    try:
        doc_service.delete_document(doc_id, hard=True)
    except Exception:
        pass
    if doc_service.get_document(doc_id) is not None:
        return False
    if storage_path and os.path.exists(storage_path):
        root = os.path.realpath(getattr(doc_service, "storage_root", "") or "")
        resolved = os.path.realpath(storage_path)
        name = os.path.basename(resolved)
        if root and resolved.startswith(root + os.sep) and doc_id in name:
            try:
                os.remove(resolved)
            except OSError:
                return False
    if storage_path and os.path.exists(storage_path):
        return False
    return True


def _empty_row(process: str) -> Dict[str, Any]:
    return {
        "process": process,
        "label": PROCESS_LABELS.get(process, process.replace("_", " ").title()),
        "uploaded": 0,
        "stored": 0,
        "by_media": {kind: 0 for kind in MEDIA_KINDS},
        "stored_by_media": {kind: 0 for kind in MEDIA_KINDS},
    }


def _finalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "process": row["process"],
        "label": row["label"],
        "uploaded": row["uploaded"],
        "stored": row["stored"],
        "by_media": dict(row["by_media"]),
        "stored_by_media": dict(row["stored_by_media"]),
    }


def _totals(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_media = {kind: 0 for kind in MEDIA_KINDS}
    stored_by_media = {kind: 0 for kind in MEDIA_KINDS}
    uploaded = 0
    stored = 0
    for row in rows:
        uploaded += row["uploaded"]
        stored += row["stored"]
        for kind in MEDIA_KINDS:
            by_media[kind] += row["by_media"][kind]
            stored_by_media[kind] += row["stored_by_media"][kind]
    return {
        "uploaded": uploaded,
        "stored": stored,
        "by_media": by_media,
        "stored_by_media": stored_by_media,
    }


def _timestamp(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value).strip()


def _endswith(name: str, suffixes: Tuple[str, ...]) -> bool:
    return any(name.endswith(suffix) for suffix in suffixes)


def _step(step_id: str, passed: bool, detail: str) -> Dict[str, Any]:
    return {"id": step_id, "passed": bool(passed), "detail": detail}
