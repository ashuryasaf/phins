"""Admin Desk — registered mailboxes, diary, and PHINS letters and tables.

The mailbox itself stays at the provider. This module is the staff desk:

* one registry row per address, starting with asaf@phins.ai, disabled until
  an admin enables it. The mailbox password is saved once in the vault
  (``services/admin_desk_mail.py``). An env var on ``secret_ref`` still counts.
  The GoDaddy token is only used to read whether that address is on the
  same account as the domain. It is never used to create a mailbox.
* a signature profile copied from the document block that desk already uses
* the meeting diary, checksummed, with contradictions kept
* letters and tables rendered once and exported as HTML, PDF, docx, xlsx,
  and csv, each file with its own sha256
* a draft that can be confirmed, and is refused while the mailbox cannot send

Records live in ``agent_artifacts`` (agent id ``admin_desk``) when the
database is on, and in the same in-memory store otherwise. A bad checksum is
not served. Nothing here writes a policy, a claim, a bill, or the ledger.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

AGENT_ID = "admin_desk"
_MAX_TABLE_ROWS = 200

_ROLE_DESK = {
    "actuary": "actuary",
    "underwriter": "underwriting",
    "claims": "claims",
    "claims_adjuster": "claims",
    "adjuster": "claims",
    "accountant": "accountant",
    "compliance": "compliance",
}
_ALL_DESK_ROLES = frozenset({"admin", "founder"})

# Identity lines taken from documents already on the platform. A drawn legal
# signature image is not included. Names that the documents do not print are
# not invented.
_PROFILE_SOURCES = (
    {
        "id": "sig-admin-v1",
        "desk": "admin",
        "version": 1,
        "source": "phins_document.py letterhead; business_plan_document.CONTACT; nda.html PHINS signature block",
        "lines": [
            "Ashury Asaf",
            "Chief Executive Officer",
            "PHINS Insurance Company Ltd.",
            "asaf@phins.ai · phins.ai",
            "Personal Health Insurance & Savings",
        ],
    },
    {
        "id": "sig-actuary-v1",
        "desk": "actuary",
        "version": 1,
        "source": "legal/financial-model.html signatory: Prepared & certified by",
        "lines": [
            "Prepared & certified by",
            "PHINS actuarial desk",
        ],
    },
    {
        "id": "sig-underwriting-v1",
        "desk": "underwriting",
        "version": 1,
        "source": "risk_reports/pdf_export.py advisor / agent signature card",
        "lines": [
            "Advisor / agent",
            "License no.: recorded on the underwriting desk",
        ],
    },
    {
        "id": "sig-claims-v1",
        "desk": "claims",
        "version": 1,
        "source": "claims_chat_service.py claim-file footer",
        "lines": [
            "PHINS claims desk",
            "PHINS claim file · confidential · identity stored as nationality, last four, and hash",
        ],
    },
    {
        "id": "sig-accountant-v1",
        "desk": "accountant",
        "version": 1,
        "source": "phins_document.py letterhead",
        "lines": [
            "PHINS accounting desk",
            "Personal Health Insurance & Savings",
        ],
    },
    {
        "id": "sig-compliance-v1",
        "desk": "compliance",
        "version": 1,
        "source": "phins_document.py letterhead",
        "lines": [
            "PHINS compliance desk",
            "Personal Health Insurance & Savings",
        ],
    },
)

_MAILBOX_SEED = (
    {"id": "mbx-admin", "desk": "admin", "role": "admin", "address": "asaf@phins.ai", "secret_ref": "PHINS_ADMIN_DESK_MAIL_ASAF"},
    {"id": "mbx-actuary", "desk": "actuary", "role": "actuary", "address": "", "secret_ref": "PHINS_ADMIN_DESK_MAIL_ACTUARY"},
    {"id": "mbx-underwriting", "desk": "underwriting", "role": "underwriter", "address": "", "secret_ref": "PHINS_ADMIN_DESK_MAIL_UNDERWRITING"},
    {"id": "mbx-claims", "desk": "claims", "role": "claims_adjuster", "address": "", "secret_ref": "PHINS_ADMIN_DESK_MAIL_CLAIMS"},
    {"id": "mbx-accountant", "desk": "accountant", "role": "accountant", "address": "", "secret_ref": "PHINS_ADMIN_DESK_MAIL_ACCOUNTANT"},
    {"id": "mbx-compliance", "desk": "compliance", "role": "compliance", "address": "", "secret_ref": "PHINS_ADMIN_DESK_MAIL_COMPLIANCE"},
)

# Same dates, times, counterparties, locations, and status as the
# pitch-dashboard diary (phins.il.meeting.diary.v8). Purpose is the
# operational line from that diary. The browser copy stays an offline cache.
# This store does not write the ledger.
_DIARY_SEED = (
    {"date": "2026-05-26", "time": "—", "counterparty": "Executive Actuary (IL · CA · US)", "location": "—", "purpose": "Engagement and technical validation.", "status": "Held"},
    {"date": "2026-06-11", "time": "10:30", "counterparty": "Investor meeting", "location": "Herzliya", "purpose": "Present platform and Israel business plan.", "status": "Scheduled"},
    {"date": "2026-07-13", "time": "11:00", "counterparty": "Chairman — AI technology development public company", "location": "TBC", "purpose": "Meeting A: strategic investment and technology co-development.", "status": "Scheduled"},
    {"date": "2026-07-13", "time": "14:15", "counterparty": "CEO — major insurance company (agents orientation)", "location": "TBC", "purpose": "Meeting B: joint company or MGA on insurer paper.", "status": "Scheduled"},
    {"date": "2026-07-27", "time": "TBC · 30 min", "counterparty": "Herzog Fox Neeman & Co. Advocates — Mrs. Neta Dorfman Raviv", "location": "TBC", "purpose": "Regulatory meeting.", "status": "Scheduled"},
    {"date": "2026-08-05", "time": "13:00 · 20 min", "counterparty": "Mrs. Orna Carni — Partner, Fintl VC", "location": "TBC", "purpose": "Introduction to PHINS.", "status": "Scheduled"},
    {"date": "2026-08-06", "time": "13:00 · 20 min", "counterparty": "Mrs. Orna Carni — Partner, Fintl VC", "location": "TBC", "purpose": "Further introduction: technology, regulation, funding, actuary.", "status": "Scheduled"},
    {"date": "2026-08-19", "time": "19:00 · 25 min", "counterparty": "Mr. Lotan Levkovitch — Partner, Grove VC", "location": "TBC", "purpose": "Public presentation at the Grove VC investor evening.", "status": "Scheduled"},
    {"date": "2026-09-24", "time": "TBC · 30 min", "counterparty": "Mr. Lotan Levkovitch — Partner, Grove VC (1:1 follow-up)", "location": "Zoom", "purpose": "Pitch follow-up to the 19 August Grove VC evening.", "status": "Scheduled"},
    {"date": "2026-10-12", "time": "TBC · 60 min", "counterparty": "Mr. Avi Ovadia — Capital Market, Insurance & Savings Authority", "location": "Jerusalem", "purpose": "Pre-ruling meeting.", "status": "Scheduled"},
    {"date": "2026-09", "time": "TBA · 60 min", "counterparty": "Aspire-Invest", "location": "TBC · Tel Aviv", "purpose": "Professional briefing. No fundraising ask.", "status": "To be scheduled"},
)


class DeskError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def stamp(record: Dict[str, Any]) -> Dict[str, Any]:
    body = {key: value for key, value in record.items() if key != "checksum"}
    stamped = dict(body)
    stamped["checksum"] = _sha256(_canonical(body))
    return stamped


def intact(record: Dict[str, Any]) -> bool:
    if not isinstance(record, dict) or "checksum" not in record:
        return False
    body = {key: value for key, value in record.items() if key != "checksum"}
    return record.get("checksum") == _sha256(_canonical(body))


def _profiles() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for source in _PROFILE_SOURCES:
        record = stamp({
            "record_type": "signature",
            **source,
        })
        out[record["id"]] = record
    return out


def profile_for_desk(desk: str) -> Dict[str, Any]:
    for record in _profiles().values():
        if record["desk"] == desk:
            return dict(record)
    raise DeskError("Signature profile not found", 404)


def secret_configured(secret_ref: str, mailbox_id: str = "") -> bool:
    if bool(str(os.environ.get(secret_ref) or "").strip()):
        return True
    if not mailbox_id:
        return False
    from services.admin_desk_mail import password_saved

    return password_saved(mailbox_id)


def _mailbox_public(record: Dict[str, Any]) -> Dict[str, Any]:
    from services.admin_desk_mail import connection_note, password_saved

    error = str(record.get("connection_error") or "")
    return {
        "id": record["id"],
        "desk": record["desk"],
        "role": record["role"],
        "address": record["address"],
        "provider": record.get("provider") or "",
        "secret_ref": record["secret_ref"],
        "secret_configured": secret_configured(record["secret_ref"], record["id"]),
        "password_saved": password_saved(record["id"]),
        "enabled": bool(record.get("enabled")),
        "mail_product": record.get("mail_product") or "",
        "imap_host": record.get("imap_host") or "",
        "connection_state": record.get("connection_state") or "",
        "connection_error": error,
        "connection_note": connection_note(error),
        "signature_id": record["signature_id"],
        "signature_sha256": record["signature_sha256"],
        "checksum": record["checksum"],
    }


def _role(role: Optional[str]) -> str:
    return str(role or "").strip().lower()


def desks_for_role(role: Optional[str]) -> Optional[List[str]]:
    """``None`` means every desk. An empty list means this role has no desk."""
    normalized = _role(role)
    if normalized in _ALL_DESK_ROLES:
        return None
    desk = _ROLE_DESK.get(normalized)
    if not desk:
        return []
    return [desk]


def _visible(record_desk: str, role: Optional[str]) -> bool:
    desks = desks_for_role(role)
    if desks is None:
        return True
    return record_desk in desks


_LOCK = threading.Lock()
_STORE = None
_SEEDED = False


def _new_store():
    from services.hydrated_store import artifact_store

    return artifact_store(
        "admin_desk.records",
        agent_id=AGENT_ID,
        kind="record",
        subject=lambda record: (record.get("record_type"), record.get("desk") or record.get("id")),
    )


def reset_for_tests() -> None:
    """Drop the process store so a test starts from the seed."""
    global _STORE, _SEEDED
    from services.hydrated_store import reset_shared_stores

    reset_shared_stores()
    with _LOCK:
        _STORE = None
        _SEEDED = False


def _store():
    global _STORE, _SEEDED
    with _LOCK:
        if _STORE is None:
            _STORE = _new_store()
        store = _STORE
        if not _SEEDED:
            _seed(store)
            _SEEDED = True
        return store


def _seed(store) -> None:
    profiles = _profiles()
    if store.get("mbx-admin") is None:
        for spec in _MAILBOX_SEED:
            profile = profiles["sig-" + spec["desk"] + "-v1"]
            store[spec["id"]] = stamp({
                "record_type": "mailbox",
                "id": spec["id"],
                "desk": spec["desk"],
                "role": spec["role"],
                "address": spec["address"],
                "provider": "",
                "secret_ref": spec["secret_ref"],
                "enabled": False,
                "signature_id": profile["id"],
                "signature_sha256": profile["checksum"],
            })
    existing = [key for key in store.keys() if str(key).startswith("diary-seed-")]
    if not existing:
        for index, row in enumerate(_DIARY_SEED, start=1):
            record_id = f"diary-seed-{index:02d}"
            store[record_id] = stamp({
                "record_type": "diary",
                "id": record_id,
                "desk": "admin",
                **row,
                "origin": "seed",
                "revisions": [],
                "created_at": "2026-10-12T00:00:00+00:00",
            })


def _read(store, key: str) -> Optional[Dict[str, Any]]:
    record = store.get(key)
    if record is None:
        return None
    if not intact(record):
        _note_fault(store, key, "checksum mismatch")
        return None
    return record


def _note_fault(store, key: str, reason: str) -> None:
    fault_id = "fault-" + _sha256(f"{key}:{reason}")[:16]
    if store.get(fault_id) is not None:
        return
    store[fault_id] = stamp({
        "record_type": "fault",
        "id": fault_id,
        "subject_id": key,
        "reason": reason,
        "created_at": _now(),
    })


def _audit(actor: str, action: str, entity_id: str, details: Dict[str, Any]) -> str:
    safe = {}
    for key, value in details.items():
        lowered = key.lower()
        if "password" in lowered or ("secret" in lowered and key != "secret_ref"):
            continue
        safe[key] = value
    record_id = "aud-" + uuid.uuid4().hex[:12]
    _store()[record_id] = stamp({
        "record_type": "audit",
        "id": record_id,
        "actor": actor or "unknown",
        "action": action,
        "entity_id": entity_id,
        "details": safe,
        "created_at": _now(),
    })
    try:
        from services.audit_service import AuditService
        AuditService().log(actor or "unknown", action, "admin_desk", entity_id, safe)
    except Exception:
        pass
    return record_id


def _records(store, record_type: str) -> List[Dict[str, Any]]:
    found = []
    for key in list(store.keys()):
        record = _read(store, key)
        if record and record.get("record_type") == record_type:
            found.append(record)
    found.sort(key=lambda item: str(item.get("id")))
    return found


def list_mailboxes(role: Optional[str]) -> List[Dict[str, Any]]:
    if desks_for_role(role) == []:
        raise DeskError("Desk access required", 403)
    store = _store()
    rows = []
    for record in _records(store, "mailbox"):
        if _visible(record["desk"], role):
            rows.append(_mailbox_public(record))
    return rows


def get_mailbox(mailbox_id: str, role: Optional[str]) -> Dict[str, Any]:
    if desks_for_role(role) == []:
        raise DeskError("Desk access required", 403)
    record = _read(_store(), mailbox_id)
    if not record or record.get("record_type") != "mailbox" or not _visible(record["desk"], role):
        raise DeskError("Mailbox not found", 404)
    return record


def set_mailbox_address(mailbox_id: str, address: str, role: Optional[str], actor: str) -> Dict[str, Any]:
    if _role(role) != "admin":
        raise DeskError("Admin access required", 403)
    record = get_mailbox(mailbox_id, "admin")
    clean = str(address or "").strip().lower()
    if clean and ("@" not in clean or clean.startswith("@") or clean.endswith("@")):
        raise DeskError("Enter a full email address", 400)
    updated = dict(record)
    updated["address"] = clean
    stored = stamp(updated)
    _store()[mailbox_id] = stored
    _audit(actor, "admin_desk.mailbox_address", mailbox_id, {"address": clean, "desk": record["desk"]})
    return _mailbox_public(stored)


def set_mailbox_enabled(mailbox_id: str, enabled: bool, role: Optional[str], actor: str) -> Dict[str, Any]:
    if _role(role) != "admin":
        raise DeskError("Admin access required", 403)
    record = get_mailbox(mailbox_id, "admin")
    if enabled and not secret_configured(record["secret_ref"], record["id"]):
        raise DeskError("secret_not_configured", 409)
    if enabled and not str(record.get("address") or "").strip():
        raise DeskError("Set the mailbox address before enabling it", 409)
    updated = dict(record)
    updated["enabled"] = bool(enabled)
    stored = stamp(updated)
    _store()[mailbox_id] = stored
    _audit(actor, "admin_desk.mailbox_enabled", mailbox_id, {
        "enabled": bool(enabled),
        "secret_ref": record["secret_ref"],
        "address": record.get("address") or "",
    })
    return _mailbox_public(stored)


def mailbox_attribution(mailbox_id: str, role: Optional[str]) -> Dict[str, Any]:
    """Read-only GoDaddy check for one registered address. Admin only."""
    if _role(role) != "admin":
        raise DeskError("Admin access required", 403)
    record = get_mailbox(mailbox_id, "admin")
    address = str(record.get("address") or "").strip()
    if not address:
        raise DeskError("Set the mailbox address before checking it", 409)
    from services.admin_desk_mail import attribute_mailbox, password_saved

    report = attribute_mailbox(address)
    report["id"] = record["id"]
    report["password_saved"] = password_saved(record["id"])
    return report


def save_mailbox_password(
    mailbox_id: str,
    password: str,
    role: Optional[str],
    actor: str,
    *,
    dns_lookup=None,
    imap_factory=None,
    transport=None,
) -> Dict[str, Any]:
    """Store the mailbox password once, then connect only if the host accepts it."""
    if _role(role) != "admin":
        raise DeskError("Admin access required", 403)
    record = get_mailbox(mailbox_id, "admin")
    address = str(record.get("address") or "").strip()
    if not address:
        raise DeskError("Set the mailbox address before saving a password", 409)
    from services.admin_desk_mail import (
        MailVaultError,
        attribute_mailbox,
        connect_saved_password,
        save_password,
    )

    try:
        save_password(record["id"], password)
    except MailVaultError as exc:
        raise DeskError(exc.message, exc.status) from exc
    report = attribute_mailbox(address, transport=transport, dns_lookup=dns_lookup)
    try:
        code = connect_saved_password(record["id"], address, report, imap_factory=imap_factory)
    except MailVaultError as exc:
        raise DeskError(exc.message, exc.status) from exc
    updated = dict(record)
    updated["mail_product"] = report.get("mail_product") or ""
    updated["imap_host"] = report.get("imap_host") or ""
    updated["connection_state"] = "connected" if code == "connected" else "saved"
    updated["connection_error"] = "" if code == "connected" else code
    updated["connection_checked_at"] = _now()
    stored = stamp(updated)
    _store()[record["id"]] = stored
    _audit(actor, "admin_desk.password_saved", record["id"], {
        "address": address,
        "mail_product": updated["mail_product"],
        "connection_state": updated["connection_state"],
        "connection_error": updated["connection_error"],
    })
    return _mailbox_public(stored)


def list_diary(role: Optional[str]) -> List[Dict[str, Any]]:
    if not _visible("admin", role):
        raise DeskError("Diary access required", 403)
    rows = _records(_store(), "diary")
    rows.sort(key=lambda item: (str(item.get("date")), str(item.get("id"))))
    return [_diary_public(row) for row in rows]


def _diary_public(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": record["id"],
        "date": record.get("date") or "",
        "time": record.get("time") or "",
        "counterparty": record.get("counterparty") or "",
        "location": record.get("location") or "",
        "purpose": record.get("purpose") or "",
        "status": record.get("status") or "",
        "origin": record.get("origin") or "",
        "checksum": record["checksum"],
        "revisions": list(record.get("revisions") or []),
    }


def _diary_body(fields: Dict[str, Any]) -> Dict[str, str]:
    return {
        "date": str(fields.get("date") or "").strip(),
        "time": str(fields.get("time") or "").strip(),
        "counterparty": str(fields.get("counterparty") or "").strip(),
        "location": str(fields.get("location") or "").strip(),
        "purpose": str(fields.get("purpose") or "").strip(),
        "status": str(fields.get("status") or "Scheduled").strip() or "Scheduled",
    }


def add_diary(fields: Dict[str, Any], role: Optional[str], actor: str) -> Dict[str, Any]:
    if _role(role) not in _ALL_DESK_ROLES:
        raise DeskError("Admin access required", 403)
    body = _diary_body(fields)
    if not body["counterparty"]:
        raise DeskError("Counterparty is required", 400)
    record_id = "diary-" + uuid.uuid4().hex[:12]
    stored = stamp({
        "record_type": "diary",
        "id": record_id,
        "desk": "admin",
        **body,
        "origin": "user",
        "revisions": [],
        "created_at": _now(),
    })
    _store()[record_id] = stored
    _audit(actor, "admin_desk.diary_add", record_id, {"checksum": stored["checksum"]})
    return _diary_public(stored)


def import_diary(rows: Sequence[Dict[str, Any]], role: Optional[str], actor: str) -> Dict[str, Any]:
    if _role(role) not in _ALL_DESK_ROLES:
        raise DeskError("Admin access required", 403)
    if not isinstance(rows, list):
        raise DeskError("rows must be a list", 400)
    batch_hash = _sha256(_canonical([_diary_body(row) for row in rows]))
    store = _store()
    marker_id = "import-" + batch_hash[:20]
    if _read(store, marker_id) is not None:
        return {"duplicate": True, "batch_hash": batch_hash, "added": 0, "contradictions": 0}
    added = 0
    contradictions = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        body = _diary_body(row)
        incoming_id = str(row.get("id") or "").strip()
        if incoming_id:
            current = _read(store, incoming_id)
            if current and current.get("record_type") == "diary":
                current_body = _diary_body(current)
                if current_body != body:
                    contradiction_id = "contradiction-" + uuid.uuid4().hex[:12]
                    store[contradiction_id] = stamp({
                        "record_type": "contradiction",
                        "id": contradiction_id,
                        "diary_id": incoming_id,
                        "server": current_body,
                        "server_checksum": current["checksum"],
                        "incoming": body,
                        "created_at": _now(),
                    })
                    contradictions += 1
                continue
        record_id = incoming_id or ("diary-" + _sha256(_canonical(body))[:12])
        if _read(store, record_id) is not None:
            continue
        store[record_id] = stamp({
            "record_type": "diary",
            "id": record_id,
            "desk": "admin",
            **body,
            "origin": "import",
            "revisions": [],
            "created_at": _now(),
        })
        added += 1
    store[marker_id] = stamp({
        "record_type": "import_batch",
        "id": marker_id,
        "batch_hash": batch_hash,
        "added": added,
        "contradictions": contradictions,
        "created_at": _now(),
    })
    _audit(actor, "admin_desk.diary_import", marker_id, {
        "batch_hash": batch_hash, "added": added, "contradictions": contradictions,
    })
    return {"duplicate": False, "batch_hash": batch_hash, "added": added, "contradictions": contradictions}


def list_contradictions(role: Optional[str]) -> List[Dict[str, Any]]:
    if not _visible("admin", role):
        raise DeskError("Diary access required", 403)
    return [
        {
            "id": row["id"],
            "diary_id": row.get("diary_id"),
            "server_checksum": row.get("server_checksum"),
            "checksum": row["checksum"],
        }
        for row in _records(_store(), "contradiction")
    ]


def _footer_lines(desk: str, address: str) -> List[str]:
    profile = profile_for_desk(desk)
    lines = list(profile["lines"])
    if address and address not in " ".join(lines):
        lines.append(address)
    return lines


def _file_record(filename: str, media_type: str, raw: bytes) -> Dict[str, Any]:
    return {
        "filename": filename,
        "media_type": media_type,
        "sha256": _sha256_bytes(raw),
        "size": len(raw),
        "data_b64": base64.b64encode(raw).decode("ascii"),
    }


def _letter_html(title: str, body: str, footer_lines: Sequence[str]) -> str:
    from services.phins_document import render_phins_document
    import html as html_lib

    paragraphs = []
    for block in str(body or "").split("\n"):
        text = block.strip()
        if text:
            paragraphs.append(f"<p>{html_lib.escape(text)}</p>")
    if not paragraphs:
        paragraphs.append("<p></p>")
    footer = "<br>".join(html_lib.escape(line) for line in footer_lines)
    return render_phins_document(
        title=title or "PHINS letter",
        eyebrow="Admin desk",
        subtitle=footer_lines[0] if footer_lines else "PHINS",
        body_html="<h1>" + html_lib.escape(title or "Letter") + "</h1>" + "".join(paragraphs),
        footer=footer,
    )


def _freeze_pdf():
    from reportlab import rl_config
    return rl_config, rl_config.invariant


def _letter_pdf(title: str, body: str, footer_lines: Sequence[str]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    rl_config, previous = _freeze_pdf()
    rl_config.invariant = 1
    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
            title=title or "PHINS letter", invariant=1,
        )
        styles = getSampleStyleSheet()
        story = [Paragraph(_xml_text(title or "Letter"), styles["Title"]), Spacer(1, 8)]
        for block in str(body or "").split("\n"):
            text = block.strip()
            if text:
                story.append(Paragraph(_xml_text(text), styles["Normal"]))
                story.append(Spacer(1, 4))
        story.append(Spacer(1, 12))
        for line in footer_lines:
            story.append(Paragraph(_xml_text(line), styles["Normal"]))
        doc.build(story)
        return buffer.getvalue()
    finally:
        rl_config.invariant = previous


def _xml_text(value: str) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _letter_docx(title: str, body: str, footer_lines: Sequence[str]) -> bytes:
    paragraphs = [title or "Letter", ""]
    paragraphs.extend(block.strip() for block in str(body or "").split("\n") if block.strip())
    paragraphs.append("")
    paragraphs.extend(footer_lines)
    body_xml = ["<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>",
                "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"><w:body>"]
    for paragraph in paragraphs:
        body_xml.append("<w:p><w:r><w:t xml:space=\"preserve\">" + _xml_text(paragraph) + "</w:t></w:r></w:p>")
    body_xml.append("<w:sectPr/></w:body></w:document>")
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        for name, payload in (
            ("[Content_Types].xml", content_types),
            ("_rels/.rels", rels),
            ("word/document.xml", "".join(body_xml)),
        ):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            package.writestr(info, payload)
    return buffer.getvalue()


def _matrix(title: str, headers: Sequence[str], rows: Sequence[Sequence[Any]], source: str) -> List[List[Any]]:
    clipped = list(rows[:_MAX_TABLE_ROWS])
    matrix: List[List[Any]] = [["source", source], ["title", title], list(headers)]
    matrix.extend([list(row) for row in clipped])
    if len(rows) > _MAX_TABLE_ROWS:
        matrix.append([f"Note: first {_MAX_TABLE_ROWS} of {len(rows)} rows"])
    return matrix


def _table_csv(matrix: Sequence[Sequence[Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for row in matrix:
        writer.writerow(list(row))
    return buffer.getvalue().encode("utf-8")


def _table_xlsx(matrix: Sequence[Sequence[Any]]) -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "PHINS table"
    for row in matrix:
        sheet.append(["" if cell is None else cell for cell in row])
    fixed = datetime(2026, 1, 1)
    workbook.properties.creator = "PHINS Admin Desk"
    workbook.properties.created = fixed
    workbook.properties.modified = fixed
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _table_pdf(title: str, matrix: Sequence[Sequence[Any]]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table

    rl_config, previous = _freeze_pdf()
    rl_config.invariant = 1
    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm,
            title=title or "PHINS table", invariant=1,
        )
        data = [[str(cell) for cell in row] for row in matrix]
        doc.build([Table(data)])
        return buffer.getvalue()
    finally:
        rl_config.invariant = previous


def create_letter(title: str, body: str, desk: str, role: Optional[str], actor: str) -> Dict[str, Any]:
    clean_desk = str(desk or "admin").strip().lower() or "admin"
    if not _visible(clean_desk, role):
        raise DeskError("Desk access required", 403)
    mailbox = _mailbox_for_desk(clean_desk)
    lines = _footer_lines(clean_desk, mailbox.get("address") or "")
    profile = profile_for_desk(clean_desk)
    slug = _sha256(_canonical({"title": title, "body": body, "lines": lines}))[:8]
    html = _letter_html(title, body, lines).encode("utf-8")
    pdf = _letter_pdf(title, body, lines)
    docx = _letter_docx(title, body, lines)
    record_id = "doc-" + uuid.uuid4().hex[:12]
    stored = stamp({
        "record_type": "document",
        "id": record_id,
        "kind": "letter",
        "desk": clean_desk,
        "title": str(title or "Letter").strip() or "Letter",
        "source": "typed on the admin desk",
        "signature_id": profile["id"],
        "signature_sha256": profile["checksum"],
        "payload_sha256": _sha256(_canonical({"title": title, "body": body, "footer": lines})),
        "files": {
            "html": _file_record(f"phins-letter-{slug}.html", "text/html", html),
            "pdf": _file_record(f"phins-letter-{slug}.pdf", "application/pdf", pdf),
            "docx": _file_record(
                f"phins-letter-{slug}.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                docx,
            ),
        },
        "created_at": _now(),
    })
    _store()[record_id] = stored
    _audit(actor, "admin_desk.letter", record_id, {
        "desk": clean_desk,
        "payload_sha256": stored["payload_sha256"],
        "signature_sha256": profile["checksum"],
    })
    return _document_public(stored)


def create_table(title: str, headers: Sequence[Any], rows: Sequence[Sequence[Any]], source: str,
                 desk: str, role: Optional[str], actor: str) -> Dict[str, Any]:
    clean_desk = str(desk or "admin").strip().lower() or "admin"
    if not _visible(clean_desk, role):
        raise DeskError("Desk access required", 403)
    citation = str(source or "").strip()
    if not citation:
        raise DeskError("A source citation is required", 400)
    clean_headers = [str(cell) for cell in (headers or [])]
    if not clean_headers:
        raise DeskError("A header row is required", 400)
    clean_rows = []
    for row in rows or []:
        if not isinstance(row, (list, tuple)):
            raise DeskError("Each row must be a list", 400)
        clean_rows.append(["" if cell is None else cell for cell in row])
    matrix = _matrix(str(title or "Table"), clean_headers, clean_rows, citation)
    slug = _sha256(_canonical(matrix))[:8]
    csv_bytes = _table_csv(matrix)
    xlsx_bytes = _table_xlsx(matrix)
    pdf_bytes = _table_pdf(str(title or "Table"), matrix)
    record_id = "doc-" + uuid.uuid4().hex[:12]
    profile = profile_for_desk(clean_desk)
    stored = stamp({
        "record_type": "document",
        "id": record_id,
        "kind": "table",
        "desk": clean_desk,
        "title": str(title or "Table").strip() or "Table",
        "source": citation,
        "signature_id": profile["id"],
        "signature_sha256": profile["checksum"],
        "payload_sha256": _sha256(_canonical(matrix)),
        "files": {
            "csv": _file_record(f"phins-table-{slug}.csv", "text/csv", csv_bytes),
            "xlsx": _file_record(
                f"phins-table-{slug}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                xlsx_bytes,
            ),
            "pdf": _file_record(f"phins-table-{slug}.pdf", "application/pdf", pdf_bytes),
        },
        "created_at": _now(),
    })
    _store()[record_id] = stored
    _audit(actor, "admin_desk.table", record_id, {
        "desk": clean_desk,
        "source": citation,
        "payload_sha256": stored["payload_sha256"],
    })
    return _document_public(stored)


def _mailbox_for_desk(desk: str) -> Dict[str, Any]:
    for record in _records(_store(), "mailbox"):
        if record["desk"] == desk:
            return record
    return {"address": ""}


def _document_public(record: Dict[str, Any]) -> Dict[str, Any]:
    files = {}
    for fmt, info in (record.get("files") or {}).items():
        files[fmt] = {
            "filename": info.get("filename"),
            "media_type": info.get("media_type"),
            "sha256": info.get("sha256"),
            "size": info.get("size"),
        }
    return {
        "id": record["id"],
        "kind": record["kind"],
        "desk": record["desk"],
        "title": record["title"],
        "source": record.get("source") or "",
        "signature_id": record.get("signature_id"),
        "signature_sha256": record.get("signature_sha256"),
        "payload_sha256": record.get("payload_sha256"),
        "checksum": record["checksum"],
        "files": files,
        "created_at": record.get("created_at"),
    }


def list_documents(role: Optional[str]) -> List[Dict[str, Any]]:
    if desks_for_role(role) == []:
        raise DeskError("Desk access required", 403)
    rows = []
    for record in _records(_store(), "document"):
        if _visible(record.get("desk") or "admin", role):
            rows.append(_document_public(record))
    rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return rows


def document_file(document_id: str, fmt: str, role: Optional[str]) -> Dict[str, Any]:
    record = _read(_store(), document_id)
    if not record or record.get("record_type") != "document" or not _visible(record.get("desk") or "admin", role):
        raise DeskError("Document not found", 404)
    info = (record.get("files") or {}).get(fmt)
    if not info:
        raise DeskError("That file format is not on this document", 404)
    raw = base64.b64decode(info["data_b64"])
    digest = _sha256_bytes(raw)
    if digest != info.get("sha256"):
        _note_fault(_store(), document_id, f"{fmt} bytes do not match sha256")
        raise DeskError("File checksum mismatch", 409)
    return {
        "id": document_id,
        "format": fmt,
        "filename": info["filename"],
        "media_type": info["media_type"],
        "sha256": digest,
        "data_b64": info["data_b64"],
    }


def create_draft(mailbox_id: str, to_address: str, subject: str, body: str,
                 attachment_ids: Sequence[str], role: Optional[str], actor: str) -> Dict[str, Any]:
    mailbox = get_mailbox(mailbox_id, role)
    if _role(role) not in _ALL_DESK_ROLES and _role(role) not in _ROLE_DESK:
        raise DeskError("Desk access required", 403)
    recipient = str(to_address or "").strip().lower()
    if "@" not in recipient:
        raise DeskError("Enter the recipient address", 400)
    lines = _footer_lines(mailbox["desk"], mailbox.get("address") or "")
    preview = str(body or "").rstrip() + "\n\n" + "\n".join(lines)
    attachments = []
    store = _store()
    for attachment_id in attachment_ids or []:
        document = _read(store, str(attachment_id))
        if not document or document.get("record_type") != "document":
            raise DeskError("Attachment not found", 404)
        if not _visible(document.get("desk") or "admin", role):
            raise DeskError("Attachment not found", 404)
        attachments.append({
            "id": document["id"],
            "payload_sha256": document.get("payload_sha256"),
            "checksum": document["checksum"],
        })
    record_id = "drf-" + uuid.uuid4().hex[:12]
    stored = stamp({
        "record_type": "draft",
        "id": record_id,
        "mailbox_id": mailbox["id"],
        "desk": mailbox["desk"],
        "from": mailbox.get("address") or "",
        "to": recipient,
        "subject": str(subject or "").strip(),
        "body": str(body or ""),
        "preview": preview,
        "preview_sha256": _sha256(preview),
        "signature_id": mailbox["signature_id"],
        "signature_sha256": mailbox["signature_sha256"],
        "attachments": attachments,
        "status": "draft",
        "send_error": "",
        "created_at": _now(),
    })
    store[record_id] = stored
    _audit(actor, "admin_desk.draft", record_id, {
        "mailbox_id": mailbox["id"],
        "preview_sha256": stored["preview_sha256"],
    })
    return _draft_public(stored)


def send_draft(draft_id: str, role: Optional[str], actor: str) -> Dict[str, Any]:
    store = _store()
    record = _read(store, draft_id)
    if not record or record.get("record_type") != "draft" or not _visible(record.get("desk") or "admin", role):
        raise DeskError("Draft not found", 404)
    if record.get("status") == "failed":
        return _draft_public(record)
    mailbox = get_mailbox(record["mailbox_id"], role)
    if not mailbox.get("enabled") or not secret_configured(mailbox["secret_ref"], mailbox["id"]):
        updated = dict(record)
        updated["status"] = "failed"
        updated["send_error"] = "mailbox_not_ready"
        stored = stamp(updated)
        store[draft_id] = stored
        _audit(actor, "admin_desk.send_refused", draft_id, {
            "mailbox_id": mailbox["id"],
            "reason": "mailbox_not_ready",
            "preview_sha256": record.get("preview_sha256"),
        })
        return _draft_public(stored)
    # A configured mailbox still does not send in this build. The provider
    # adapter is the next phase. Refusing here keeps a confirmed draft from
    # leaving the platform through an unfinished path.
    updated = dict(record)
    updated["status"] = "failed"
    updated["send_error"] = "send_not_connected"
    stored = stamp(updated)
    store[draft_id] = stored
    _audit(actor, "admin_desk.send_refused", draft_id, {
        "mailbox_id": mailbox["id"],
        "reason": "send_not_connected",
        "preview_sha256": record.get("preview_sha256"),
    })
    return _draft_public(stored)


def _draft_public(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": record["id"],
        "mailbox_id": record["mailbox_id"],
        "desk": record["desk"],
        "from": record.get("from") or "",
        "to": record.get("to") or "",
        "subject": record.get("subject") or "",
        "preview": record.get("preview") or "",
        "preview_sha256": record.get("preview_sha256"),
        "signature_id": record.get("signature_id"),
        "signature_sha256": record.get("signature_sha256"),
        "attachments": list(record.get("attachments") or []),
        "status": record.get("status"),
        "send_error": record.get("send_error") or "",
        "checksum": record["checksum"],
        "sent": False,
    }


def list_drafts(role: Optional[str]) -> List[Dict[str, Any]]:
    if desks_for_role(role) == []:
        raise DeskError("Desk access required", 403)
    rows = []
    for record in _records(_store(), "draft"):
        if _visible(record.get("desk") or "admin", role):
            rows.append(_draft_public(record))
    return rows


def overview(role: Optional[str]) -> Dict[str, Any]:
    mailboxes = list_mailboxes(role)
    diary = list_diary(role) if _visible("admin", role) else []
    contradictions = list_contradictions(role) if _visible("admin", role) else []
    documents = list_documents(role)
    drafts = list_drafts(role)
    ready_mail = any(item["enabled"] and item["secret_configured"] for item in mailboxes)
    phases = [
        {"id": "0", "name": "Registry and signature", "state": "ready"},
        {"id": "1", "name": "Diary", "state": "ready"},
        {"id": "2", "name": "Remember mail", "state": "ready" if ready_mail else "waiting_for_credential"},
        {"id": "3", "name": "Calendar", "state": "waiting_for_credential"},
        {"id": "4", "name": "Missions", "state": "waiting_for_credential"},
        {"id": "5", "name": "Send and reply", "state": "waiting_for_credential"},
        {"id": "6", "name": "Every registered mailbox", "state": "ready"},
        {"id": "7", "name": "Letters and tables", "state": "ready"},
    ]
    faults = [
        {"id": row["id"], "subject_id": row.get("subject_id"), "reason": row.get("reason")}
        for row in _records(_store(), "fault")
    ] if _role(role) in _ALL_DESK_ROLES else []
    return {
        "agent_id": AGENT_ID,
        "mailboxes": mailboxes,
        "diary": diary,
        "contradictions": contradictions,
        "documents": documents,
        "drafts": drafts,
        "faults": faults,
        "phases": phases,
        "send_connected": False,
        "can_manage_mail": _role(role) == "admin",
    }
