"""Pipeline network, desk-to-desk shares, and the meeting next-move brain.

The hierarchy is the operating pipeline. A desk may hand work to another
associate desk. Customers and the regulator stay on the map and do not
receive those shares. The next move is read from intact diary rows and
unanswered shares. It recommends. It does not write the ledger, reprice,
or change a meeting.

Unauthorized-use events are a bounded ring of denials plus counts the
caller already has. The report names the path and the role. It does not
store a request body, a password, or an identity number.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

# Order is the pipeline, not a rank of people. Oversight sits first because
# every other desk reports there. Customer and regulator are visible and
# are not share targets.
PIPELINE = (
    {"stage": "oversight", "order": 0, "desk": "admin", "roles": ("admin", "founder"), "share": True},
    {"stage": "development", "order": 1, "desk": "development", "roles": ("development",), "share": True},
    {"stage": "actuarial", "order": 2, "desk": "actuary", "roles": ("actuary",), "share": True},
    {"stage": "underwriting", "order": 3, "desk": "underwriting", "roles": ("underwriter",), "share": True},
    {"stage": "claims", "order": 4, "desk": "claims", "roles": ("claims", "claims_adjuster", "adjuster"), "share": True},
    {"stage": "billing", "order": 5, "desk": "accountant", "roles": ("accountant",), "share": True},
    {"stage": "compliance", "order": 6, "desk": "compliance", "roles": ("compliance",), "share": True},
    {"stage": "distribution", "order": 7, "desk": "agent", "roles": ("agent",), "share": False},
    {"stage": "supply", "order": 8, "desk": "supplier", "roles": ("supplier",), "share": False},
    {"stage": "customer", "order": 9, "desk": "", "roles": ("customer",), "share": False},
    {"stage": "regulator", "order": 10, "desk": "", "roles": ("regulator",), "share": False},
)

_ROLE_STAGE = {}
for _stage in PIPELINE:
    for _role in _stage["roles"]:
        _ROLE_STAGE[_role] = _stage

SHAREABLE_DESKS = tuple(stage["desk"] for stage in PIPELINE if stage["share"] and stage["desk"])
_DENIALS: deque = deque(maxlen=200)
_DENIAL_REPEAT = 3
_LOGIN_BURST = 3
_MOVE_CAP = 12
_PRIVATE_PREFIXES = (
    "/api/health-wallet",
    "/api/pipeline/deposit",
    "/api/pipeline/settings",
    "/api/savings/",
    "/api/marketplace/wallet",
)


def desk_for_role(role: Optional[str]) -> str:
    stage = _ROLE_STAGE.get(str(role or "").strip().lower())
    if not stage:
        return ""
    return stage["desk"]


def share_targets(from_desk: str) -> List[str]:
    origin = str(from_desk or "").strip()
    if origin not in SHAREABLE_DESKS:
        return []
    return [desk for desk in SHAREABLE_DESKS if desk != origin]


def _public_user(raw: Dict[str, Any]) -> Dict[str, Any]:
    role = str(raw.get("role") or "").strip().lower()
    stage = _ROLE_STAGE.get(role)
    username = str(raw.get("username") or "").strip()
    return {
        "username": username,
        "name": str(raw.get("name") or username),
        "role": role,
        "desk": stage["desk"] if stage else "",
        "stage": stage["stage"] if stage else "unassigned",
        "order": stage["order"] if stage else 99,
        "online": bool(raw.get("online")),
        "active": raw.get("active") is not False,
    }


def project_directory(users: Iterable[Dict[str, Any]], role: Optional[str]) -> Dict[str, Any]:
    """Active users on the pipeline. Secrets on the input are dropped."""
    caller = str(role or "").strip().lower()
    admin = caller in {"admin", "founder"}
    caller_desk = "admin" if caller == "founder" else desk_for_role(caller)
    visible_desks = set(SHAREABLE_DESKS) if admin else set(share_targets(caller_desk)) | ({caller_desk} if caller_desk else set())
    projected = []
    counts: Dict[str, int] = {stage["stage"]: 0 for stage in PIPELINE}
    counts["unassigned"] = 0
    for raw in users:
        if not isinstance(raw, dict):
            continue
        user = _public_user(raw)
        if not user["active"] or not user["username"]:
            continue
        counts[user["stage"]] = counts.get(user["stage"], 0) + 1
        if admin or (user["desk"] and user["desk"] in visible_desks):
            projected.append(user)
    projected.sort(key=lambda item: (item["order"], item["username"]))
    stages = [
        {
            "stage": stage["stage"],
            "order": stage["order"],
            "desk": stage["desk"],
            "share": stage["share"],
            "count": counts.get(stage["stage"], 0),
        }
        for stage in PIPELINE
    ]
    return {
        "stages": stages,
        "users": projected,
        "stage_counts": counts,
        "share_targets": share_targets(caller_desk),
        "caller_desk": caller_desk,
    }


def _meeting_day(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return ""


def _within(day: str, today: str, window: int) -> bool:
    try:
        left = date.fromisoformat(day)
        start = date.fromisoformat(today)
    except ValueError:
        return False
    return 0 <= (left - start).days <= window


def next_move_rows(
    diary: Iterable[Dict[str, Any]],
    shares: Iterable[Dict[str, Any]],
    acked_ids: Iterable[str],
    desk: str,
    today: str,
) -> Dict[str, Any]:
    """Advisory moves from intact meetings and unanswered shares."""
    acked = set(acked_ids)
    moves: List[Dict[str, Any]] = []
    for share in shares:
        if share.get("id") in acked:
            continue
        subject = str(share.get("subject") or "").strip()
        if share.get("to_desk") == desk:
            moves.append({
                "kind": "answer_share",
                "source_id": share.get("id"),
                "source_checksum": share.get("checksum") or "",
                "desk": desk,
                "text": "Answer {origin}: {subject}".format(
                    origin=share.get("from_desk") or "a desk",
                    subject=subject,
                ),
            })
        elif share.get("from_desk") == desk:
            moves.append({
                "kind": "follow_up",
                "source_id": share.get("id"),
                "source_checksum": share.get("checksum") or "",
                "desk": desk,
                "text": "Follow up with {target}: {subject}".format(
                    target=share.get("to_desk") or "the desk",
                    subject=subject,
                ),
            })
    for row in diary:
        if str(row.get("status") or "") != "Scheduled":
            continue
        day = _meeting_day(str(row.get("date") or ""))
        if not day:
            continue
        counterparty = str(row.get("counterparty") or "").strip()
        purpose = str(row.get("purpose") or "").strip()
        if day < today:
            text = "Record the outcome of {who} ({day}). {purpose}".format(
                who=counterparty, day=day, purpose=purpose,
            ).strip()
            kind = "close_meeting"
        elif _within(day, today, 7):
            text = "Prepare the brief for {who} ({day}). {purpose}".format(
                who=counterparty, day=day, purpose=purpose,
            ).strip()
            kind = "prepare_meeting"
        else:
            continue
        moves.append({
            "kind": kind,
            "source_id": row.get("id"),
            "source_checksum": row.get("checksum") or "",
            "desk": desk,
            "text": text,
        })
    order = {"answer_share": 0, "follow_up": 1, "close_meeting": 2, "prepare_meeting": 3}
    moves.sort(key=lambda item: (order.get(item["kind"], 9), str(item.get("source_id"))))
    truncated = len(moves) > _MOVE_CAP
    kept = moves[:_MOVE_CAP]
    if not kept:
        kept = [{
            "kind": "clear",
            "source_id": "desk",
            "source_checksum": "",
            "desk": desk,
            "text": "No open meeting or desk share needs a next step.",
        }]
    return {
        "advisory": True,
        "writes_ledger": False,
        "today": today,
        "truncated": truncated,
        "moves": kept,
    }


def note_access_denial(actor: str, role: str, method: str, path: str, reason: str) -> None:
    """Remember one denied call. The body and the query string are not stored."""
    clean_path = str(path or "").split("?", 1)[0][:180]
    if not clean_path:
        return
    _DENIALS.append({
        "actor": str(actor or "")[:80],
        "role": str(role or "").strip().lower()[:40],
        "method": str(method or "GET").upper()[:8],
        "path": clean_path,
        "reason": str(reason or "")[:80],
        "at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    })


def reset_denials() -> None:
    _DENIALS.clear()


def _anomaly(kind: str, subject: str, count: int, evidence: str) -> Dict[str, Any]:
    body = {
        "kind": kind,
        "subject": subject[:120],
        "count": int(count),
        "evidence": evidence[:180],
    }
    body["checksum"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return body


def unauthorized_report(
    failed_logins: Optional[Dict[str, Any]] = None,
    malicious_count: int = 0,
) -> Dict[str, Any]:
    """Anomalies from denials already recorded and counts the caller supplies."""
    buckets: Dict[str, int] = {}
    private_hits: Dict[str, int] = {}
    for event in _DENIALS:
        key = "{role} {method} {path}".format(**event)
        buckets[key] = buckets.get(key, 0) + 1
        path = event["path"]
        if any(path == prefix or path.startswith(prefix) for prefix in _PRIVATE_PREFIXES):
            private_hits[key] = private_hits.get(key, 0) + 1
    anomalies = []
    for key, count in sorted(buckets.items()):
        if count >= _DENIAL_REPEAT:
            anomalies.append(_anomaly("repeated_access_denial", key, count, "access denial ring"))
    for key, count in sorted(private_hits.items()):
        anomalies.append(_anomaly("customer_private_reach", key, count, "staff or other role reached a customer-private path"))
    for subject, info in sorted((failed_logins or {}).items()):
        count = info.get("count", 0) if isinstance(info, dict) else 0
        try:
            count = int(count)
        except (TypeError, ValueError):
            count = 0
        label = str(subject)[:80]
        if "password" in label.lower() or count < _LOGIN_BURST:
            continue
        anomalies.append(_anomaly("login_failure_burst", label, count, "failed login counter"))
    try:
        malicious = int(malicious_count or 0)
    except (TypeError, ValueError):
        malicious = 0
    if malicious > 0:
        anomalies.append(_anomaly("malicious_request", "request gate", malicious, "malicious attempt counter"))
    digest = hashlib.sha256(
        json.dumps(
            [{"kind": item["kind"], "subject": item["subject"], "count": item["count"]} for item in anomalies],
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "denial_count": len(_DENIALS),
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
        "checksum": digest,
    }
