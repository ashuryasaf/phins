"""HTTP surface for the Admin Desk.

Routes live under ``/api/admin/ai-agents/desk`` so they do not collide with
AgentOS ``/api/admin/agents``. Handlers stay thin: the service owns the
checksums, the role scope, and the refusal to send.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from services.admin_desk_service import DeskError, document_file, overview
from services.admin_desk_service import (
    add_diary,
    create_draft,
    create_letter,
    create_table,
    import_diary,
    send_draft,
    set_mailbox_address,
    set_mailbox_enabled,
)

PREFIX = "/api/admin/ai-agents/desk"


def _actor(session: Optional[Dict]) -> str:
    if not session:
        return ""
    return str(session.get("username") or session.get("email") or session.get("role") or "")


def _role(session: Optional[Dict]) -> str:
    if not session:
        return ""
    return str(session.get("role") or "")


def _call(fn):
    try:
        return 200, fn()
    except DeskError as exc:
        return exc.status, {"error": exc.message}


def dispatch_get(path: str, session: Optional[Dict], query_params: Optional[Dict]) -> Optional[Tuple[int, Dict]]:
    if path != PREFIX and not path.startswith(PREFIX + "/"):
        return None
    if not session:
        return 401, {"error": "Authentication required"}
    tail = path[len(PREFIX):].strip("/")
    if tail == "":
        return _call(lambda: overview(_role(session)))
    parts = [part for part in tail.split("/") if part]
    if len(parts) == 2 and parts[0] == "documents":
        fmt = ""
        raw = (query_params or {}).get("format")
        if isinstance(raw, (list, tuple)):
            fmt = str(raw[0]) if raw else ""
        elif raw:
            fmt = str(raw)
        if not fmt:
            return 400, {"error": "format is required"}
        return _call(lambda: document_file(parts[1], fmt, _role(session)))
    return 404, {"error": "Desk route was not found"}


def dispatch_post(path: str, session: Optional[Dict], body: Optional[Dict]) -> Optional[Tuple[int, Dict]]:
    if path != PREFIX and not path.startswith(PREFIX + "/"):
        return None
    if not session:
        return 401, {"error": "Authentication required"}
    payload = body if isinstance(body, dict) else {}
    role = _role(session)
    actor = _actor(session)
    tail = path[len(PREFIX):].strip("/")
    parts = [part for part in tail.split("/") if part]

    if parts == ["mailboxes"]:
        return _call(lambda: set_mailbox_address(
            str(payload.get("id") or ""), str(payload.get("address") or ""), role, actor,
        ))
    if len(parts) == 3 and parts[0] == "mailboxes" and parts[2] == "enable":
        return _call(lambda: set_mailbox_enabled(parts[1], bool(payload.get("enabled")), role, actor))
    if parts == ["diary"]:
        return _call(lambda: add_diary(payload, role, actor))
    if parts == ["diary", "import"]:
        return _call(lambda: import_diary(payload.get("rows") or [], role, actor))
    if parts == ["documents", "letter"]:
        return _call(lambda: create_letter(
            str(payload.get("title") or ""),
            str(payload.get("body") or ""),
            str(payload.get("desk") or "admin"),
            role,
            actor,
        ))
    if parts == ["documents", "table"]:
        return _call(lambda: create_table(
            str(payload.get("title") or ""),
            payload.get("headers") or [],
            payload.get("rows") or [],
            str(payload.get("source") or ""),
            str(payload.get("desk") or "admin"),
            role,
            actor,
        ))
    if parts == ["drafts"]:
        return _call(lambda: create_draft(
            str(payload.get("mailbox_id") or ""),
            str(payload.get("to") or ""),
            str(payload.get("subject") or ""),
            str(payload.get("body") or ""),
            payload.get("attachment_ids") or [],
            role,
            actor,
        ))
    if len(parts) == 3 and parts[0] == "drafts" and parts[2] == "send":
        return _call(lambda: send_draft(parts[1], role, actor))
    return 404, {"error": "Desk route was not found"}
