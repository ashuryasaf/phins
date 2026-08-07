"""
Durable persistence for the actuary dashboard store.

Dashboard adjustments to underwriting config (including age-banded L:D ratios)
and active table versions must survive process restart. This module serializes
the in-memory ``ActuarialTablesStore`` to a JSON file path controlled by
``PHINS_ACTUARIAL_STATE_PATH`` (default: ``data/actuarial_store_state.json``).

Fail-open relative to pricing: load/save errors are logged and never crash
the portal. Callers may surface a ``persistence_warning`` on API responses.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("phins.actuarial_persistence")

DEFAULT_STATE_PATH = os.environ.get(
    "PHINS_ACTUARIAL_STATE_PATH",
    os.path.join("data", "actuarial_store_state.json"),
)


def _state_path() -> Path:
    raw = os.environ.get("PHINS_ACTUARIAL_STATE_PATH", DEFAULT_STATE_PATH)
    path = Path(raw)
    if not path.is_absolute():
        # Resolve relative to repo root when possible
        root = Path(__file__).resolve().parents[1]
        path = root / path
    return path


def serialize_store(store: Any) -> Dict[str, Any]:
    cfg = store.config
    return {
        "schema_version": 1,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "current_version": store.current_version,
        "config": asdict(cfg) if hasattr(cfg, "__dataclass_fields__") else dict(cfg or {}),
        "versions": store.versions,
    }


def persist_actuarial_store(store: Any, path: Optional[str] = None) -> str:
    """Write store state to disk. Returns the absolute path written."""
    target = Path(path) if path else _state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = serialize_store(store)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    os.replace(tmp, target)
    logger.info("Persisted actuarial store to %s (tables=%s config=%s)",
                target, store.current_version, getattr(store.config, "config_version", "?"))
    return str(target)


def load_actuarial_store(store: Any, path: Optional[str] = None) -> bool:
    """Load persisted state into an existing store instance. Returns True if loaded."""
    target = Path(path) if path else _state_path()
    if not target.exists():
        return False
    try:
        with open(target, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception as exc:
        logger.warning("Failed to read actuarial state %s: %s", target, exc)
        return False

    versions = payload.get("versions") or {}
    if isinstance(versions, dict) and versions:
        store.versions = versions
    current = payload.get("current_version")
    if current and current in store.versions:
        store.current_version = current

    cfg_data = payload.get("config") or {}
    if cfg_data:
        try:
            from services.actuarial_service import UnderwritingConfig
            # Only pass known fields
            fields = getattr(UnderwritingConfig, "__dataclass_fields__", {})
            kwargs = {k: v for k, v in cfg_data.items() if k in fields}
            # Ensure new band fields exist even on older snapshots
            kwargs.setdefault("disability_share_of_life", 0.25)
            kwargs.setdefault("disability_share_of_life_post65", 1.0)
            kwargs.setdefault("life_share_of_coverage", 1.0)
            kwargs.setdefault("life_share_of_coverage_post65", 0.25)
            kwargs.setdefault("disability_band_age", 65)
            kwargs.setdefault("pre65_disability_continues_policy", True)
            kwargs.setdefault("post_disability_life_share_of_face", 0.75)
            kwargs.setdefault("post_disability_premium_factor", 1.0)
            kwargs.setdefault("post65_claims_mutually_exclusive", True)
            for _k in (
                "smoker_mortality_factor", "smoker_disability_factor",
                "former_smoker_mortality_factor", "former_smoker_disability_factor",
                "nonsmoker_mortality_factor", "nonsmoker_disability_factor",
                "male_mortality_factor", "male_disability_factor",
                "female_mortality_factor", "female_disability_factor",
            ):
                kwargs.setdefault(_k, 1.0)
            kwargs.setdefault(
                "ethnicity_mortality_factors",
                {"caucasian": 1.0, "african": 1.0, "hispanic": 1.0, "asian": 1.0, "other": 1.0},
            )
            kwargs.setdefault(
                "ethnicity_disability_factors",
                {"caucasian": 1.0, "african": 1.0, "hispanic": 1.0, "asian": 1.0, "other": 1.0},
            )
            kwargs.setdefault("config_version", "cfg_v1")
            store.config = UnderwritingConfig(**kwargs)
        except Exception as exc:
            logger.warning("Failed to restore actuarial config: %s", exc)
            return False

    logger.info("Loaded actuarial store from %s (tables=%s config=%s)",
                target, store.current_version, getattr(store.config, "config_version", "?"))
    return True
