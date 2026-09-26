"""Regulator inquiries, kept apart from the public solutions contact queue.

One open conversation per regulation account and outlined subject. Further
messages append. An identical last message is a duplicate and adds nothing.
The sealed outline is never read or written here, and customer identifiers
are never accepted.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Tuple

# The regulation dashboard's main sections. Public solution interests
# (assessments, billing, smart contracts, and the rest) are a different list.
SUBJECTS: Tuple[Tuple[str, str], ...] = (
    ("pricing", "Pricing kernel"),
    ("underwriting", "Underwriting"),
    ("claims", "Claims"),
    ("investments", "Investments"),
    ("health", "Health"),
    ("agents", "Agent BI"),
    ("integrity", "Integrity"),
)
SUBJECT_LABELS = dict(SUBJECTS)

PUBLIC_CONVERSATION_URL = "https://www.phins.ai/solutions.html#contact"
CHANNEL = "regulator"
MAX_MESSAGE_CHARS = 2000
_INQUIRY_ID_RE = re.compile(r"^RINQ-\d{6}-[A-F0-9]{8}$")
_RECORD_KEYS = (
    "id",
    "subject",
    "subject_label",
    "status",
    "opened_by",
    "channel",
    "created_at",
    "updated_at",
    "messages",
)


class InquiryError(ValueError):
    """A regulator inquiry the caller must not store."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def subject_catalog() -> List[Dict[str, str]]:
    """Outlined subjects a regulator may open an inquiry on."""
    return [{"id": subject_id, "label": label} for subject_id, label in SUBJECTS]


def clean_message(raw: Any) -> str:
    """Conversation text with controls removed. Newlines stay."""
    if not isinstance(raw, str):
        raise InquiryError("Message is required")
    text = raw.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 32)
    text = text.strip()
    if not text:
        raise InquiryError("Message is required")
    if len(text) > MAX_MESSAGE_CHARS:
        raise InquiryError(f"Message must be {MAX_MESSAGE_CHARS} characters or fewer")
    return text


def clean_subject(raw: Any) -> str:
    """An outlined subject id. Public solution interests are refused."""
    if not isinstance(raw, str):
        raise InquiryError("Select an outlined subject")
    subject = raw.strip()
    if subject not in SUBJECT_LABELS:
        raise InquiryError("Select an outlined subject")
    return subject


def clone_record(record: Mapping[str, Any]) -> Dict[str, Any]:
    """A copy limited to the inquiry fields. Extra keys are dropped."""
    messages = []
    for turn in record.get("messages") or []:
        if not isinstance(turn, Mapping):
            continue
        messages.append({
            "at": turn.get("at"),
            "by": turn.get("by"),
            "body": turn.get("body"),
        })
    cloned = {key: record.get(key) for key in _RECORD_KEYS}
    cloned["messages"] = messages
    return cloned


def apply_open_inquiry(
    records: Mapping[str, Mapping[str, Any]],
    username: str,
    subject: Any,
    message: Any,
    now: str,
    new_id: str,
) -> Tuple[str, Dict[str, Any]]:
    """Plan one inquiry write without mutating ``records``.

    Returns ``(action, record)`` where action is ``created``, ``appended``,
    or ``duplicate``. ``opened_by`` is the signed-in username only.
    """
    opened_by = str(username or "").strip()
    if not opened_by:
        raise InquiryError("Authentication required", 401)
    subject_id = clean_subject(subject)
    body = clean_message(message)
    stamp = str(now or "").strip()
    if not stamp:
        raise InquiryError("Inquiry could not be recorded", 500)

    existing = _open_for(records.values(), opened_by, subject_id)
    if existing is None:
        inquiry_id = str(new_id or "").strip()
        if not _INQUIRY_ID_RE.match(inquiry_id):
            raise InquiryError("Inquiry could not be recorded", 500)
        record = {
            "id": inquiry_id,
            "subject": subject_id,
            "subject_label": SUBJECT_LABELS[subject_id],
            "status": "open",
            "opened_by": opened_by,
            "channel": CHANNEL,
            "created_at": stamp,
            "updated_at": stamp,
            "messages": [{"at": stamp, "by": opened_by, "body": body}],
        }
        return "created", record

    messages = [
        {"at": turn.get("at"), "by": turn.get("by"), "body": turn.get("body")}
        for turn in (existing.get("messages") or [])
        if isinstance(turn, Mapping)
    ]
    last_body = messages[-1]["body"] if messages else ""
    cloned = clone_record(existing)
    if last_body == body:
        return "duplicate", cloned
    cloned["messages"] = messages + [{"at": stamp, "by": opened_by, "body": body}]
    cloned["updated_at"] = stamp
    cloned["status"] = "open"
    cloned["channel"] = CHANNEL
    cloned["opened_by"] = opened_by
    cloned["subject"] = subject_id
    cloned["subject_label"] = SUBJECT_LABELS[subject_id]
    return "appended", cloned


def _open_for(
    records: Iterable[Mapping[str, Any]],
    opened_by: str,
    subject_id: str,
) -> Mapping[str, Any] | None:
    """The latest open inquiry for this account and subject."""
    matches = [
        rec for rec in records
        if rec.get("opened_by") == opened_by
        and rec.get("subject") == subject_id
        and rec.get("status") == "open"
    ]
    if not matches:
        return None
    return max(matches, key=lambda rec: str(rec.get("updated_at") or ""))
