"""Read-only ERP/MGA posture for the cyber desk.

The autopilot and ``/api/security/dashboard`` already score the request
edge. This module scores the money controls those surfaces did not see:
Money Gate, the books-tied certificate, period close, trust seals, kernel
pins, and the platform-ledger chain.

Every read is fail-closed. A reader that throws, a missing stage, or a
value that is not ``up`` / ``watch`` / ``down`` is ``down``. Nothing here
issues a certificate, restores a pin, posts a journal row, or closes a
session.
"""

from __future__ import annotations

import threading
from datetime import date
from typing import Any, Callable, Dict, Mapping, Optional

BOOK_CONTROLS = (
    "money_gate",
    "books_tied",
    "period_close",
    "trust_account",
    "kernel_pins",
    "ledger_chain",
)

# Down-weights. The sum is capped so a red book alone stays under the
# session-drop recommendation (score 40) in ``score_pipeline``.
_DOWN_WEIGHTS = {
    "money_gate": 15,
    "books_tied": 10,
    "period_close": 10,
    "trust_account": 10,
    "kernel_pins": 10,
    "ledger_chain": 15,
}
BOOKS_SCORE_CAP = 35

_IN_FORCE = frozenset({"active", "in_force", "issued", "approved"})

_LOCK = threading.Lock()
_LAST: Dict[str, Any] = {}

_LABELS = {
    "money_gate": "Money Gate (critical books checks)",
    "books_tied": "Books-tied certificate",
    "period_close": "Period close",
    "trust_account": "Trust account",
    "kernel_pins": "Kernel pins",
    "ledger_chain": "Platform ledger chain",
}


def _note(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    return cleaned[:240]


def _state(value: Any) -> str:
    token = str(value or "").strip().lower()
    if token in ("up", "watch", "down"):
        return token
    return "down"


def points_for(stages: Mapping[str, Any]) -> int:
    total = 0
    for name, weight in _DOWN_WEIGHTS.items():
        if _state(stages.get(name)) == "down":
            total += weight
    return min(BOOKS_SCORE_CAP, total)


def score_books(raw: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Public posture. Recomputes points from stages. Drops seals and amounts."""
    supplied: Mapping[str, Any] = {}
    already_scored = False
    if isinstance(raw, Mapping):
        maybe = raw.get("stages")
        if isinstance(maybe, Mapping):
            supplied = maybe
            already_scored = True
        else:
            supplied = raw
    stages: Dict[str, str] = {}
    findings = []
    for name in BOOK_CONTROLS:
        cell = supplied.get(name)
        note = ""
        if isinstance(cell, Mapping):
            state = _state(cell.get("state"))
            note = _note(cell.get("note") or "")
        else:
            state = _state(cell) if name in supplied else "down"
        if name not in supplied:
            state = "down"
            note = note or f"{_LABELS[name]} was not read."
        stages[name] = state
        if note and state != "up":
            findings.append(note)
        elif state == "down":
            findings.append(f"{_LABELS[name]} is not green.")
    if already_scored and isinstance(raw, Mapping) and isinstance(raw.get("findings"), list):
        findings = [_note(item) for item in raw["findings"] if _note(item)]
    recommendations = []
    if any(state == "down" for state in stages.values()):
        recommendations.append(
            "Money controls are red. Do not release a withdrawal, settle "
            "commission, or pay a claim until they are green. Autopilot does "
            "not move money and does not close sessions."
        )
    elif any(state == "watch" for state in stages.values()):
        recommendations.append(
            "A money control is watching. It is not refusing a move by itself."
        )
    protections = []
    for name in BOOK_CONTROLS:
        state = stages[name]
        mark = {"up": "ACTIVE", "watch": "WATCH", "down": "INACTIVE"}[state]
        protections.append(f"{_LABELS[name]}: {mark}")
    return {
        "stages": stages,
        "findings": findings,
        "recommendations": recommendations,
        "protections": protections,
        "points": points_for(stages),
    }


def unreadable_posture() -> Dict[str, Any]:
    raw = {
        name: {"state": "down", "note": f"{_LABELS[name]} could not be read."}
        for name in BOOK_CONTROLS
    }
    scored = score_books(raw)
    scored["readable"] = False
    return scored


def last_books_posture() -> Dict[str, Any]:
    with _LOCK:
        if not _LAST:
            return unreadable_posture()
        return dict(_LAST)


def _remember(posture: Mapping[str, Any]) -> None:
    with _LOCK:
        _LAST.clear()
        _LAST.update(posture)


def _money_note(verdict: Mapping[str, Any]) -> Dict[str, str]:
    failed = [str(item) for item in (verdict.get("failed_checks") or []) if str(item or "").strip()]
    source = str(verdict.get("source") or "")
    if (not verdict.get("ok")) or source == "books_unreadable" or "books_unreadable" in failed:
        if source == "books_unreadable" or "books_unreadable" in failed:
            return {"state": "down", "note": "Money Gate could not read the books."}
        names = ", ".join(sorted(set(failed))[:8])
        note = "Money Gate critical checks are red."
        if names:
            note = f"Money Gate critical checks are red: {names}."
        return {"state": "down", "note": note}
    if verdict.get("enforced") is False:
        return {
            "state": "watch",
            "note": "Money Gate is not enforcing. Critical checks that were read are green.",
        }
    return {"state": "up", "note": "Money Gate critical checks are green and enforcement is on."}


def _default_money() -> Dict[str, str]:
    from services.erp.money_gate import evaluate_money_gate

    verdict = evaluate_money_gate(operation="cyber_assess")
    return _money_note(verdict.as_dict())


def _books_tied_note(report: Mapping[str, Any]) -> Dict[str, str]:
    if report.get("readable") is False:
        return {"state": "down", "note": "Books-tied certificate could not be read."}
    intact = report.get("intact") is True
    fresh = report.get("fresh") is True
    required = report.get("required") is True
    reason = str(report.get("reason") or "")
    if not intact or "tamper" in reason:
        return {"state": "down", "note": "Books-tied certificate failed its seal."}
    if fresh:
        return {"state": "up", "note": "Books-tied certificate is fresh."}
    if required:
        return {
            "state": "down",
            "note": "Books-tied certificate is not fresh enough for a high-value move.",
        }
    return {
        "state": "watch",
        "note": "Books-tied certificate is not required in this process.",
    }


def _default_books_tied(ledger: Any) -> Dict[str, str]:
    if ledger is None:
        return {"state": "down", "note": "Books-tied certificate could not be read."}
    from services.erp.books_tied import status_report

    report = status_report(ledger)
    if not isinstance(report, Mapping):
        return {"state": "down", "note": "Books-tied certificate could not be read."}
    return _books_tied_note(report)


def _default_period() -> Dict[str, str]:
    from services.erp import period_close as period_close

    today = date.today()
    period_id = period_close.period_id_for(today.year, today.month)
    rows = {}
    for row in period_close.list_periods():
        if isinstance(row, Mapping) and row.get("id"):
            rows[str(row.get("id"))] = row
    current = rows.get(period_id)
    if current is None:
        return {
            "state": "watch",
            "note": "This month has no period row. Posts are not hard-closed.",
        }
    status = str(current.get("status") or "")
    pack = period_close.get_close_pack(period_id)
    if status == period_close.STATUS_HARD:
        if not pack:
            return {"state": "down", "note": "Hard-closed month has no close pack."}
        if not period_close.verify_close_pack(pack).get("ok"):
            return {"state": "down", "note": "Hard-close pack failed its seal."}
        return {"state": "up", "note": "Current month is hard-closed and the pack seal matches."}
    if status == period_close.STATUS_SOFT:
        if pack and not period_close.verify_close_pack(pack).get("ok"):
            return {"state": "down", "note": "Soft-close pack failed its seal."}
        return {
            "state": "watch",
            "note": "Current month is soft-closed. Posts are still accepted.",
        }
    if status == period_close.STATUS_OPEN:
        return {"state": "up", "note": "Current month is open."}
    return {"state": "down", "note": "Period status is not a known state."}


def _default_trust() -> Dict[str, str]:
    from services.mga.trust import reconcile_trust

    report = reconcile_trust()
    if not isinstance(report, Mapping):
        return {"state": "down", "note": "Trust Recon could not be read."}
    codes = []
    for item in report.get("findings") or []:
        if isinstance(item, Mapping):
            code = str(item.get("code") or "").strip()
            if code:
                codes.append(code)
    if "trust_seal_withheld" in codes:
        return {
            "state": "down",
            "note": "A trust movement failed its seal and was withheld from the balance.",
        }
    if "trust_deficit" in codes:
        return {
            "state": "down",
            "note": "Trust Recon reports a deficit. No cash was invented to close it.",
        }
    if report.get("ok") is True:
        return {"state": "up", "note": "Trust movements that were read kept their seals."}
    if "bank_balance_unavailable" in codes:
        return {
            "state": "watch",
            "note": "Trust book was read. No bank balance is on file to tie.",
        }
    return {"state": "down", "note": "Trust Recon is not green."}


def _policy_rows(policies: Any) -> list:
    if policies is None:
        raise RuntimeError("policies unread")
    values = policies.values() if hasattr(policies, "values") else policies
    return list(values)


def _kernel_note(policies: Any) -> Dict[str, str]:
    broken = 0
    missing = 0
    for policy in _policy_rows(policies):
        if not isinstance(policy, Mapping):
            continue
        status = str(policy.get("status") or "").strip().lower()
        if status not in _IN_FORCE:
            continue
        if policy.get("kernel_pin_intact") is False:
            broken += 1
            continue
        pin = policy.get("kernel_pin")
        if not isinstance(pin, Mapping) or not pin:
            missing += 1
    if broken:
        return {
            "state": "down",
            "note": f"{broken} in-force policy pin(s) failed their seal and were not applied.",
        }
    if missing:
        return {
            "state": "watch",
            "note": f"{missing} in-force policy(ies) have no kernel pin.",
        }
    return {"state": "up", "note": "In-force policies that have a pin kept it."}


def _ledger_note(ledger: Any) -> Dict[str, str]:
    if ledger is None or not hasattr(ledger, "get_integrity_summary"):
        return {"state": "down", "note": "Platform ledger chain could not be read."}
    summary = ledger.get_integrity_summary()
    if not isinstance(summary, Mapping):
        return {"state": "down", "note": "Platform ledger chain could not be read."}
    if summary.get("chain_valid") is True:
        return {"state": "up", "note": "Platform ledger chain verifies."}
    broken = summary.get("broken_links")
    count = len(broken) if isinstance(broken, list) else None
    note = "Platform ledger chain is not valid."
    if count is not None:
        note = f"Platform ledger chain is not valid. {count} broken link(s)."
    return {"state": "down", "note": note}


def collect_books_posture(
    *,
    policies: Any = None,
    ledger: Any = None,
    money_reader: Optional[Callable[[], Mapping[str, Any]]] = None,
    books_tied_reader: Optional[Callable[[Any], Mapping[str, Any]]] = None,
    period_reader: Optional[Callable[[], Mapping[str, Any]]] = None,
    trust_reader: Optional[Callable[[], Mapping[str, Any]]] = None,
    kernel_reader: Optional[Callable[[Any], Mapping[str, Any]]] = None,
    ledger_reader: Optional[Callable[[Any], Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Read the six controls. A failed reader is ``down`` and is not repaired."""
    readers = {
        "money_gate": lambda: (money_reader or _default_money)(),
        "books_tied": lambda: (books_tied_reader or _default_books_tied)(ledger),
        "period_close": lambda: (period_reader or _default_period)(),
        "trust_account": lambda: (trust_reader or _default_trust)(),
        "kernel_pins": lambda: (kernel_reader or _kernel_note)(policies),
        "ledger_chain": lambda: (ledger_reader or _ledger_note)(ledger),
    }
    raw: Dict[str, Dict[str, str]] = {}
    try:
        for name, reader in readers.items():
            try:
                cell = reader()
            except Exception:
                cell = {"state": "down", "note": f"{_LABELS[name]} could not be read."}
            if not isinstance(cell, Mapping):
                cell = {"state": "down", "note": f"{_LABELS[name]} could not be read."}
            raw[name] = {
                "state": _state(cell.get("state")),
                "note": _note(cell.get("note") or f"{_LABELS[name]} could not be read."),
            }
        scored = score_books(raw)
        scored["readable"] = True
    except Exception:
        scored = unreadable_posture()
    _remember(scored)
    return scored
