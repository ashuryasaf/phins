"""
Canonical Agent Helpers
=======================
Shared defensive conversion and status-normalisation helpers for agent
modules (docs/agent_operations_optimization_design.md §A1).

Several agent modules carry private copies of ``_safe_float`` / ``_status``
with *slightly* different semantics (comma stripping, bool handling,
space-to-underscore). To keep data integrity exact, the canonical helpers
expose those variations as explicit keyword options so each adopting module
can request behaviour identical to the copy it replaces. Adoption is verified
by parity tests (``tests/test_agent_helpers.py``).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional


def safe_float(value: Any, default: float = 0.0, *,
               strip_commas: bool = True, bool_as_int: bool = True,
               finite_only: bool = False) -> float:
    """Convert arbitrary values to float without raising.

    ``strip_commas`` renders the value through ``str()`` and removes
    thousands separators and surrounding whitespace before parsing
    (``"1,234.5" -> 1234.5``; ``b"12" -> default``). With it off, the value
    is passed to ``float()`` verbatim, matching modules whose copy did not
    strip. ``bool_as_int`` maps ``True/False -> 1.0/0.0`` explicitly
    (Python's ``float(True)`` already does this; the flag exists so the
    intent is visible and testable). ``finite_only`` returns ``default`` for
    ``nan``/``inf`` (the trading-engine copy's semantics).
    """
    try:
        if value is None:
            return default
        if isinstance(value, bool):
            result = float(int(value)) if bool_as_int else float(value)
        elif strip_commas:
            result = float(str(value).replace(",", "").strip())
        else:
            result = float(value)
        if finite_only and not math.isfinite(result):
            return default
        return result
    except (TypeError, ValueError, OverflowError):
        return default


def safe_int(value: Any, default: int = 0, *, via_float: bool = True) -> int:
    """Convert arbitrary values to int without raising.

    ``via_float`` parses through ``float`` first so ``"12.0"`` and ``12.7``
    become ``12`` (the semantics of the marketing-agent copy). With it off,
    ``int(value)`` is used directly.
    """
    try:
        if value is None:
            return default
        if via_float:
            return int(float(value))
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def status_lower(value: Any, *, underscore_spaces: bool = False,
                 strip: bool = True, falsy_as_empty: bool = False) -> str:
    """Normalise a status-like value for comparison.

    Accepts either a raw value or a dict with a ``status`` key.

    * ``strip`` trims surrounding whitespace (the agent-module copies do;
      the ``web_portal.server`` helpers do not).
    * ``underscore_spaces`` maps spaces to underscores
      (``"Under Review" -> "under_review"``).
    * ``falsy_as_empty`` treats any falsy value (``0``, ``""``, ``None``) as
      empty, matching ``(item.get('status') or '')`` / ``str(value or "")``.
      With it off only ``None`` is empty, so ``0 -> "0"``.
    """
    if isinstance(value, dict):
        value = value.get('status')
    if value is None or (falsy_as_empty and not value):
        return ""
    text = str(value)
    if strip:
        text = text.strip()
    text = text.lower()
    if underscore_spaces:
        text = text.replace(" ", "_")
    return text


def _server_status(value: Any) -> str:
    return status_lower(value, underscore_spaces=True, strip=False, falsy_as_empty=True)


def status_eq(item: Any, *statuses: str) -> bool:
    """Case-insensitive, space/underscore-insensitive status equality
    (identical semantics to ``web_portal.server.status_eq``)."""
    current = _server_status(item)
    return current in [_server_status(s) for s in statuses]


def status_in(item: Any, statuses: Iterable[str]) -> bool:
    """Case-insensitive membership check (identical semantics to
    ``web_portal.server.status_in``)."""
    current = _server_status(item)
    return current in [_server_status(s) for s in statuses]


def utc_now_iso(*, timespec: Optional[str] = None, zulu: bool = False) -> str:
    """UTC timestamp in ISO-8601. ``zulu`` renders ``Z`` instead of ``+00:00``."""
    now = datetime.now(timezone.utc)
    text = now.isoformat(timespec=timespec) if timespec else now.isoformat()
    if zulu:
        text = text.replace("+00:00", "Z")
    return text


def get_status_lower(item: Dict) -> str:
    """Identical semantics to ``web_portal.server.get_status_lower``."""
    return _server_status(item)


__all__ = [
    'safe_float', 'safe_int', 'status_lower', 'status_eq', 'status_in',
    'utc_now_iso', 'get_status_lower',
]
