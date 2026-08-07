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


def _map_tobacco_to_smoking(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in ("yes", "current", "smoker", "y", "true", "1"):
        return "smoker"
    if s in ("former", "ex", "ex_smoker", "ex-smoker"):
        return "former"
    if s in ("no", "never", "nonsmoker", "non-smoker", "n", "false", "0"):
        return "nonsmoker"
    return s or None


def extract_application_pricing_inputs(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Pull age/term/ADL/gender/smoking/ethnicity from a new-application payload."""
    personal = payload.get("personal_info") or payload.get("personal") or {}
    health = payload.get("health") or {}
    questionnaire = payload.get("questionnaire") or {}
    coverage = payload.get("coverage") or {}

    smoking = (
        payload.get("smoking_status")
        or payload.get("smoker")
        or health.get("tobacco")
        or questionnaire.get("smoke")
        or questionnaire.get("tobacco")
    )
    gender = (
        payload.get("gender")
        or personal.get("gender")
        or questionnaire.get("gender")
    )
    ethnicity = (
        payload.get("ethnicity")
        or personal.get("ethnicity")
        or questionnaire.get("ethnicity")
    )
    age = payload.get("age") or payload.get("customer_age") or personal.get("age") or 35
    term = (
        payload.get("term_years")
        or payload.get("coverage_years")
        or coverage.get("coverageYears")
        or coverage.get("term_years")
        or 20
    )
    adl = payload.get("adl_level") or payload.get("adl") or 5
    return {
        "age": int(age or 35),
        "term_years": int(term or 20),
        "adl_level": int(adl or 5),
        "gender": gender,
        "smoking_status": _map_tobacco_to_smoking(smoking),
        "ethnicity": ethnicity,
        "coverage_amount": float(
            payload.get("coverage_amount")
            or coverage.get("coverageAmount")
            or coverage.get("amount")
            or 0
        ),
        "type": payload.get("type") or "life",
    }


def is_kernel_billing_enabled() -> bool:
    """Kernel bills new life policies outside test mode unless explicitly disabled."""
    raw = os.environ.get("PHINS_KERNEL_BILLING_ENABLED")
    if raw is not None and str(raw).strip() != "":
        return _truthy(raw)
    # Preserve flat-formula expectations under pytest / PHINS_TEST_MODE.
    if _truthy(os.environ.get("PHINS_TEST_MODE")):
        return False
    return True


def price_application_with_kernel(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Price a new application via the actuarial kernel + persisted pricing params.

    Returns a premium dict with integrity metadata, or None if type unmapped /
    kernel unavailable. Never raises.
    """
    try:
        inputs = extract_application_pricing_inputs(payload)
        product_id = map_policy_type_to_product(inputs.get("type") or "")
        if not product_id:
            return None
        if float(inputs.get("coverage_amount") or 0) <= 0:
            return None

        from services.actuarial_service import get_actuarial_store
        from services.pricing_kernel import (
            PricingCustomer,
            get_product,
            price_policy,
            pricing_config_from_underwriting,
            table_set_from_store,
        )

        store = get_actuarial_store()
        # Pure-risk default for new applications (savings is an optional add-on).
        savings_rate = float(
            payload.get("savings_rate")
            or (payload.get("phins_allocation") or {}).get("savings_pct")
            or 0.0
        )
        # phins_allocation.savings_pct is often 0-100; normalize when > 1.
        if savings_rate > 1.0:
            savings_rate = savings_rate / 100.0
        # Application savings allocation is portfolio routing, not risk markup —
        # price base risk cover at savings_rate=0 unless explicitly requested.
        if "savings_rate" not in payload:
            savings_rate = 0.0

        cfg = pricing_config_from_underwriting(store.config, savings_rate=savings_rate)
        tables = table_set_from_store(store)
        product = get_product(product_id)
        gender = inputs.get("gender")
        smoking = inputs.get("smoking_status")
        ethnicity = inputs.get("ethnicity")
        customer = PricingCustomer(
            age=int(inputs["age"]),
            coverage=float(inputs["coverage_amount"]),
            term_years=int(inputs["term_years"]),
            adl_level=int(inputs["adl_level"]),
            gender=gender,
            smoking_status=smoking,
            ethnicity=ethnicity,
            cohort={
                "gender": str(gender or "").lower(),
                "ethnicity": str(ethnicity or "").lower(),
                "smoker": str(smoking or "").lower(),
            },
        )
        components = price_policy(customer, product, tables, cfg)
        monthly = float(components.monthly_premium)
        return {
            "annual": float(components.annual_premium),
            "monthly": monthly,
            "quarterly": round(monthly * 3 * 0.97, 2),
            "pricing_source": "pricing_kernel",
            "integrity_hash": components.integrity_hash,
            "product_id": components.product_id,
            "tables_version": components.tables_version,
            "config_version": components.config_version,
            "demographic_mortality_factor": components.demographic_mortality_factor,
            "demographic_disability_factor": components.demographic_disability_factor,
            "smoking_status_used": components.smoking_status_used,
            "gender_used": components.gender_used,
            "ethnicity_used": components.ethnicity_used,
            "life_sum_used": components.life_sum_used,
            "disability_sum_used": components.disability_sum_used,
            "components": components.as_dict(),
        }
    except Exception as exc:
        logger.warning("kernel application pricing failed: %s", exc, exc_info=True)
        return None


def build_shadow_snapshot(
    policy: Dict[str, Any],
    flat_premiums: Dict[str, float],
) -> Optional[Dict[str, Any]]:
    """Build an immutable shadow snapshot dict, or None if type unmapped."""
    product_id = map_policy_type_to_product(policy.get("type") or "")
    if not product_id:
        return None

    from services.actuarial_service import get_contract_specification

    # Merge application demographics into the policy view for kernel pricing.
    merged = dict(policy)
    inputs = extract_application_pricing_inputs(policy)
    for key in ("age", "term_years", "adl_level", "gender", "smoking_status", "ethnicity"):
        if inputs.get(key) is not None and merged.get(key) in (None, "", 0):
            merged[key] = inputs[key]
        elif key in ("gender", "smoking_status", "ethnicity") and inputs.get(key):
            merged[key] = inputs[key]

    kernel_price = price_application_with_kernel(merged)
    if not kernel_price:
        return None
    kernel = kernel_price.get("components") or {}

    flat_annual = float(flat_premiums.get("annual") or policy.get("annual_premium") or 0)
    flat_monthly = float(flat_premiums.get("monthly") or policy.get("monthly_premium") or 0)
    kernel_annual = float(kernel_price.get("annual") or 0)
    kernel_monthly = float(kernel_price.get("monthly") or 0)

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
        "demographic_mortality_factor": kernel.get("demographic_mortality_factor"),
        "demographic_disability_factor": kernel.get("demographic_disability_factor"),
        "smoking_status_used": kernel.get("smoking_status_used"),
        "gender_used": kernel.get("gender_used"),
        "ethnicity_used": kernel.get("ethnicity_used"),
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
