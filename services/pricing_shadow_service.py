"""
Shadow dual-run of the pricing kernel beside flat-rate issuance.

When ``PHINS_PRICING_SHADOW_ENABLED`` is truthy, policy create computes a
kernel ``PremiumSnapshot`` (age-banded L:D, versioned tables/config) without
changing billed premiums. Fail-open: never breaks create.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("phins.pricing_shadow")

MAX_SNAPSHOTS_IN_MEMORY = int(os.environ.get("PHINS_MAX_PRICING_SNAPSHOTS", "20000"))

POLICY_TYPE_TO_PRODUCT = {
    "life": "phins_pure_risk_adjustable",
    "health": "phins_pure_risk_adjustable",
    "phins_unified": "phins_pure_risk_adjustable",
}

_LOCK = threading.RLock()
_SNAPSHOTS: List[Dict[str, Any]] = []
_BY_POLICY: Dict[str, List[str]] = {}


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def is_shadow_enabled() -> bool:
    return _truthy(os.environ.get("PHINS_PRICING_SHADOW_ENABLED"))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _payload_checksum(body: Dict[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def map_policy_type_to_product(policy_type: str) -> Optional[str]:
    return POLICY_TYPE_TO_PRODUCT.get(str(policy_type or "").strip().lower())


def build_shadow_snapshot(
    policy: Dict[str, Any],
    flat_premiums: Dict[str, float],
) -> Optional[Dict[str, Any]]:
    """Build an immutable shadow snapshot dict, or None if type unmapped."""
    product_id = map_policy_type_to_product(policy.get("type") or "")
    if not product_id:
        return None

    from services.actuarial_service import get_actuarial_store, get_contract_specification
    from services.pricing_kernel import (
        PricingCustomer,
        get_product,
        price_policy,
        pricing_config_from_underwriting,
        table_set_from_store,
    )

    store = get_actuarial_store()
    tables = table_set_from_store(store)
    cfg = pricing_config_from_underwriting(store.config)
    product = get_product(product_id)

    age = int(policy.get("age") or 35)
    coverage = float(policy.get("coverage_amount") or 0)
    term = int(
        policy.get("term_years")
        or (policy.get("coverage") or {}).get("coverageYears")
        or 20
    )
    adl = int(policy.get("adl_level") or 5)

    customer = PricingCustomer(age=age, coverage=coverage, term_years=term, adl_level=adl)
    components = price_policy(customer, product, tables, cfg)
    kernel = components.as_dict()

    flat_annual = float(flat_premiums.get("annual") or policy.get("annual_premium") or 0)
    flat_monthly = float(flat_premiums.get("monthly") or policy.get("monthly_premium") or 0)
    kernel_annual = float(kernel.get("annual_premium") or 0)
    kernel_monthly = float(kernel.get("monthly_premium") or 0)

    contract = get_contract_specification()
    contract_version = str(contract.get("version") or "v1.0")

    body = {
        "mode": "shadow",
        "policy_id": policy.get("id"),
        "customer_id": policy.get("customer_id"),
        "product_id": product_id,
        "contract_version": contract_version,
        "tables_version": kernel.get("tables_version"),
        "config_version": kernel.get("config_version"),
        "integrity_hash": kernel.get("integrity_hash"),
        "disability_share_used": kernel.get("disability_share_used"),
        "disability_sum_used": kernel.get("disability_sum_used"),
        "flat_annual": flat_annual,
        "flat_monthly": flat_monthly,
        "kernel_annual": kernel_annual,
        "kernel_monthly": kernel_monthly,
        "delta_annual": round(kernel_annual - flat_annual, 2),
        "contract_ratios": contract.get("contract_ratios"),
        "components": kernel,
    }
    snapshot = {
        "id": f"PSNAP-{uuid.uuid4().hex[:12].upper()}",
        "created_at": _utc_now_iso(),
        "engine": "pricing_kernel",
        "engine_version": str(kernel.get("config_version") or "kernel_v1"),
        "payload_sha256": _payload_checksum(body),
        **body,
    }
    return snapshot


def record_shadow_snapshot(
    policy: Dict[str, Any],
    flat_premiums: Dict[str, float],
) -> Optional[Dict[str, Any]]:
    """Build + store snapshot. Returns snapshot or None. Never raises."""
    try:
        if not is_shadow_enabled():
            return None
        snap = build_shadow_snapshot(policy, flat_premiums)
        if not snap:
            return None
        with _LOCK:
            _SNAPSHOTS.append(snap)
            while len(_SNAPSHOTS) > MAX_SNAPSHOTS_IN_MEMORY:
                _SNAPSHOTS.pop(0)
            pid = str(snap.get("policy_id") or "")
            if pid:
                _BY_POLICY.setdefault(pid, []).append(snap["id"])
        return snap
    except Exception as exc:
        logger.warning("pricing shadow failed: %s", exc, exc_info=True)
        return None


def get_snapshots_for_policy(policy_id: str) -> List[Dict[str, Any]]:
    with _LOCK:
        ids = list(_BY_POLICY.get(policy_id, []))
        return [s for s in _SNAPSHOTS if s.get("id") in ids]


def reset_shadow_store_for_tests() -> None:
    with _LOCK:
        _SNAPSHOTS.clear()
        _BY_POLICY.clear()
