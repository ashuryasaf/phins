"""Admin-saved factor set for the PHINS Unified Business Plan.

The plan's canonical defaults live in ``services/business_plan_model.py`` and
never change here. What an admin saves on the "Adjustable factors — one
register behind every figure" panel is a *named durable scenario*: the
factor values every viewer opens on, plus the whitelist of factors an
open-link (share) viewer may still adjust. The page applies the saved set as
its baseline through ``PhinsBusinessPlan.setBaseline`` and the model API
carries the values as explicit overrides, so ``canonical`` / ``content_hash``
semantics are untouched — a saved scenario is reported as a scenario, never
as the canonical plan.

Storage: ``agent_artifacts`` (agent ``business_plan`` / kind ``settings``) in
database mode through the hydrated store, otherwise a JSON file
(``PHINS_BUSINESS_PLAN_SETTINGS_PATH`` or ``database/business_plan_settings.json``)
written atomically. Values are validated against the factor register's
bounds on write and again on read, so a corrupted or hand-edited file can
never push an out-of-range value into the plan.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from services.business_plan_model import FACTOR_INDEX, FACTORS

__all__ = [
    "BusinessPlanSettings",
    "SettingsError",
    "get_business_plan_settings",
    "reset_business_plan_settings_for_tests",
]

ARTIFACT_ID = "business_plan:settings"
_DEFAULT_FILE = "business_plan_settings.json"
_ENV_PATH = "PHINS_BUSINESS_PLAN_SETTINGS_PATH"


class SettingsError(ValueError):
    """Invalid saved-factor payload (safe to surface as an API error)."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_factors(raw: Any) -> Dict[str, float]:
    """Keep only known ids whose values sit inside the register's bounds."""
    if raw in (None, ""):
        return {}
    if not isinstance(raw, Mapping):
        raise SettingsError("factors must be an object of factor id → value.")
    clean: Dict[str, float] = {}
    for key, value in raw.items():
        fid = str(key)
        spec = FACTOR_INDEX.get(fid)
        if spec is None:
            raise SettingsError(f"Unknown factor: {fid}")
        if value in (None, ""):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise SettingsError(f"{fid} must be numeric") from exc
        if number != number or number < spec["min"] or number > spec["max"]:
            raise SettingsError(
                f"{fid} must be between {spec['min']:g} and {spec['max']:g}"
            )
        if spec["kind"] == "int":
            number = float(int(round(number)))
        if number != float(spec["default"]):
            clean[fid] = number
    return clean


def _validate_adjustable(raw: Any) -> Optional[List[str]]:
    """``None`` means every factor; a list is the whitelist (order preserved)."""
    if raw is None:
        return None
    if isinstance(raw, str):
        if raw.strip().lower() in ("", "all", "*"):
            return None
        raw = [part.strip() for part in raw.split(",") if part.strip()]
    if not isinstance(raw, (list, tuple)):
        raise SettingsError("viewer_adjustable must be a list of factor ids or 'all'.")
    seen: List[str] = []
    for item in raw:
        fid = str(item)
        if fid not in FACTOR_INDEX:
            raise SettingsError(f"Unknown factor: {fid}")
        if fid not in seen:
            seen.append(fid)
    return seen


def _sanitize(payload: Any) -> Dict[str, Any]:
    """Validate a stored/incoming document; anything invalid degrades to empty."""
    if not isinstance(payload, Mapping):
        return {"saved_factors": {}, "viewer_adjustable": None}
    try:
        factors = _validate_factors(payload.get("saved_factors"))
    except SettingsError:
        factors = {}
    try:
        adjustable = _validate_adjustable(payload.get("viewer_adjustable"))
    except SettingsError:
        adjustable = None
    out: Dict[str, Any] = {"saved_factors": factors, "viewer_adjustable": adjustable}
    for key in ("updated_at", "updated_by", "note"):
        if payload.get(key) not in (None, ""):
            out[key] = str(payload.get(key))[:200]
    return out


class _FileBackend:
    def __init__(self, path: Path):
        self._path = path

    def load(self) -> Optional[Dict[str, Any]]:
        if not self._path.exists():
            return None
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def save(self, payload: Dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        data = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(str(tmp), str(self._path))
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def clear(self) -> None:
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass


class _ArtifactBackend:
    """``agent_artifacts`` row behind the A4 hydrated store (DB mode)."""

    def __init__(self):
        from services.hydrated_store import artifact_store

        self._store = artifact_store(
            "business_plan_settings", agent_id="business_plan", kind="settings"
        )

    def load(self) -> Optional[Dict[str, Any]]:
        value = self._store.get(ARTIFACT_ID)
        return dict(value) if isinstance(value, Mapping) else None

    def save(self, payload: Dict[str, Any]) -> None:
        self._store.put(ARTIFACT_ID, dict(payload))
        # A failed durable write is retained in memory and reported by the
        # store; the admin must hear about it rather than see a false "saved".
        if ARTIFACT_ID in getattr(self._store, "_unsaved", set()):
            raise RuntimeError("Saved factors could not be stored durably.")

    def clear(self) -> None:
        try:
            del self._store[ARTIFACT_ID]
        except KeyError:
            pass


def _db_mode() -> bool:
    try:
        from services.hydrated_store import db_mode_enabled

        return bool(db_mode_enabled())
    except Exception:
        return False


class BusinessPlanSettings:
    """Durable saved-factor set + viewer whitelist with bounds validation."""

    def __init__(self, data_path: Optional[str] = None, *, backend: Any = None):
        self._lock = threading.RLock()
        if backend is not None:
            self._backend = backend
        elif data_path is None and _db_mode():
            self._backend = _ArtifactBackend()
        else:
            root = Path(__file__).resolve().parent.parent / "database"
            path = Path(data_path or os.environ.get(_ENV_PATH) or (root / _DEFAULT_FILE))
            self._backend = _FileBackend(path)

    # -- read ---------------------------------------------------------------
    def get(self) -> Dict[str, Any]:
        with self._lock:
            stored = self._backend.load()
        doc = _sanitize(stored)
        doc["has_saved"] = bool(doc["saved_factors"])
        doc["factor_count"] = len(FACTORS)
        return doc

    def saved_factors(self) -> Dict[str, float]:
        return dict(self.get()["saved_factors"])

    def viewer_adjustable(self) -> Optional[List[str]]:
        value = self.get()["viewer_adjustable"]
        return list(value) if value is not None else None

    def baseline(self) -> Dict[str, float]:
        """Every factor's effective default: saved value, else the register's."""
        saved = self.saved_factors()
        return {spec["id"]: float(saved.get(spec["id"], spec["default"])) for spec in FACTORS}

    # -- write --------------------------------------------------------------
    def save(
        self,
        *,
        factors: Any = None,
        viewer_adjustable: Any = "__keep__",
        updated_by: str = "admin",
        note: str = "",
    ) -> Dict[str, Any]:
        """Replace the saved factor set (and optionally the viewer whitelist).

        Values are validated against the register's bounds; a value equal to
        the canonical default is not stored (so the saved set is exactly the
        delta from canonical).
        """
        clean = _validate_factors(factors)
        with self._lock:
            current = _sanitize(self._backend.load())
            if viewer_adjustable == "__keep__":
                adjustable = current["viewer_adjustable"]
            else:
                adjustable = _validate_adjustable(viewer_adjustable)
            payload = {
                "version": 1,
                "saved_factors": clean,
                "viewer_adjustable": adjustable,
                "updated_at": _utc_now_iso(),
                "updated_by": str(updated_by or "admin")[:80],
                "note": str(note or "")[:200],
            }
            self._backend.save(payload)
        return self.get()

    def clear(self, *, updated_by: str = "admin") -> Dict[str, Any]:
        with self._lock:
            self._backend.clear()
        return self.get()

    # -- viewer restriction -------------------------------------------------
    def restrict_overrides(
        self, overrides: Mapping[str, Any]
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Apply the open-link whitelist to query overrides.

        Returns ``(effective_overrides, restricted_ids)``: a locked factor is
        pinned to the saved baseline (saved value, else canonical default) and
        reported under ``restricted`` when the caller tried to move it.
        """
        doc = self.get()
        whitelist = doc["viewer_adjustable"]
        baseline = {spec["id"]: float(doc["saved_factors"].get(spec["id"], spec["default"]))
                    for spec in FACTORS}
        if whitelist is None:
            return dict(overrides), []
        allowed = set(whitelist)
        effective: Dict[str, Any] = {}
        restricted: List[str] = []
        for spec in FACTORS:
            fid = spec["id"]
            base = baseline[fid]
            raw = overrides.get(fid)
            if isinstance(raw, (list, tuple)):
                raw = raw[0] if raw else None
            if fid in allowed:
                if raw not in (None, ""):
                    effective[fid] = raw
                elif base != float(spec["default"]):
                    effective[fid] = base
                continue
            # locked: pin to the baseline, note any attempt to move it
            if raw not in (None, ""):
                try:
                    if float(raw) != base:
                        restricted.append(fid)
                except (TypeError, ValueError):
                    restricted.append(fid)
            if base != float(spec["default"]):
                effective[fid] = base
        return effective, restricted


_settings: Optional[BusinessPlanSettings] = None
_settings_lock = threading.Lock()


def get_business_plan_settings(data_path: Optional[str] = None) -> BusinessPlanSettings:
    global _settings
    with _settings_lock:
        if _settings is None or data_path is not None:
            _settings = BusinessPlanSettings(data_path=data_path)
        return _settings


def reset_business_plan_settings_for_tests() -> None:
    global _settings
    with _settings_lock:
        _settings = None
