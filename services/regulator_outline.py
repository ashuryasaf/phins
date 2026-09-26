"""Read-only regulation outline.

Builds the executive book a regulation viewer is allowed to see: the active
pricing-kernel version and its published basic premiums, plus portfolio
totals for underwriting, claims, investments, health, and agent BI.

The outline is assembled field by field. Source records are never copied
through, so customer identifiers, medical notes, and credentials cannot ride
along. Every total is added twice (running sum and bucket sum) and, when the
caller supplies the canonical financial metrics, checked against those
books before the payload is hashed.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


class RegulatorIntegrityError(RuntimeError):
    """The outline could not be reconciled to the canonical books."""


# Published tariff used to illustrate the active kernel. This is not a
# customer: age/coverage/term/ADL are fixed, smoking is the standard
# nonsmoker base, and gender/ethnicity are left unset so demographic
# multipliers stay neutral.
REFERENCE_COVERAGE = 100_000.0
REFERENCE_TERM_YEARS = 20
REFERENCE_ADL = 5
REFERENCE_AGES: Sequence[int] = (30, 40, 50, 60)
REFERENCE_PRODUCT_ID = "phins_pure_risk_adjustable"

_RATE_FIELDS = frozenset({
    "age_min", "age_max", "rate_per_1000", "year", "year_min", "year_max",
    "rate", "adl", "multiplier", "benefit_pct",
})

_FORBIDDEN_KEY_PARTS = (
    "password", "passwd", "secret", "token", "salt", "api_key", "apikey",
    "national_id", "id_number", "ssn", "email", "phone", "mobile", "address",
    "medical", "diagnosis", "otp", "customer_id", "customer_name",
    "display_name", "first_name", "last_name", "username", "date_of_birth",
    "dob", "iban", "account_number", "card_number", "cvv", "authorization",
    "principal_id", "affiliation_id",
)

_EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE)
_ID_RE = re.compile(r"\b(?:CUST|CLM|POL|AGT|BILL|COMM|AGI|AFF|DOC)-[A-Z0-9][\w\-]*", re.IGNORECASE)
_SECRET_VALUE_RE = re.compile(r"(?i)(password|bearer\s|api[_-]?key|otp)")


def _money(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _round2(value: float) -> float:
    return round(float(value), 2)


def _status(item: Mapping[str, Any]) -> str:
    raw = item.get("status") or "unknown"
    return str(raw).strip().lower().replace(" ", "_") or "unknown"


def _as_list(items: Optional[Iterable[Mapping[str, Any]]]) -> List[Mapping[str, Any]]:
    if not items:
        return []
    return [item for item in items if isinstance(item, Mapping)]


def _check_double_sum(label: str, running: float, buckets: Mapping[str, float]) -> float:
    folded = _round2(sum(buckets.values()))
    running_r = _round2(running)
    if abs(folded - running_r) > 0.02:
        raise RegulatorIntegrityError(f"{label} bucket sum diverges from the running total")
    return running_r


def _count_status(items: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        key = _status(item)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _risk_band(item: Mapping[str, Any]) -> str:
    label = item.get("risk_assessment") or item.get("risk_category") or item.get("risk_score")
    if isinstance(label, str) and label.strip():
        text = label.strip().lower().replace(" ", "_")
        if text in {"low", "medium", "high", "very_high", "standard", "substandard", "decline"}:
            return text
    number = _money(label, default=-1)
    if number < 0:
        return "unscored"
    if number <= 25:
        return "0_25"
    if number <= 50:
        return "26_50"
    if number <= 75:
        return "51_75"
    return "76_100"


def aggregate_underwriting(applications: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = _as_list(applications)
    by_status = _count_status(rows)
    bands: Dict[str, int] = {}
    for row in rows:
        band = _risk_band(row)
        bands[band] = bands.get(band, 0) + 1
    return {
        "total": len(rows),
        "by_status": by_status,
        "approved": by_status.get("approved", 0),
        "pending": by_status.get("pending", 0),
        "rejected": by_status.get("rejected", 0),
        "risk_bands": dict(sorted(bands.items())),
    }


def aggregate_claims(claims: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = _as_list(claims)
    by_status = _count_status(rows)
    claimed_buckets: Dict[str, float] = {}
    approved_buckets: Dict[str, float] = {}
    claimed_running = 0.0
    approved_running = 0.0
    disbursed = 0.0
    paid_or_closed = 0.0
    pending_liability = 0.0
    for row in rows:
        status = _status(row)
        claimed = _money(row.get("claimed_amount", row.get("amount", 0)))
        approved = _money(row.get("approved_amount", row.get("amount_approved", 0)))
        claimed_buckets[status] = claimed_buckets.get(status, 0.0) + claimed
        approved_buckets[status] = approved_buckets.get(status, 0.0) + approved
        claimed_running += claimed
        approved_running += approved
        if status == "paid":
            disbursed += approved
        if status in {"paid", "closed"}:
            paid_or_closed += _money(row.get("paid_amount", row.get("approved_amount", row.get("amount_approved", 0))))
        if status in {"pending", "under_review"}:
            pending_liability += claimed
    return {
        "total": len(rows),
        "by_status": by_status,
        "claimed_amount": _check_double_sum("claims.claimed", claimed_running, claimed_buckets),
        "approved_amount": _check_double_sum("claims.approved", approved_running, approved_buckets),
        "claimed_by_status": {k: _round2(v) for k, v in sorted(claimed_buckets.items())},
        "disbursed_amount": _round2(disbursed),
        "paid_amount": _round2(paid_or_closed),
        "pending_liability": _round2(pending_liability),
        "pending": by_status.get("pending", 0) + by_status.get("under_review", 0) + by_status.get("medical_assessment", 0),
        "approved": by_status.get("approved", 0),
        "rejected": by_status.get("rejected", 0),
    }


def aggregate_policies(policies: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = _as_list(policies)
    by_type: Dict[str, int] = {}
    premium_buckets: Dict[str, float] = {}
    active_premium = 0.0
    coverage = 0.0
    investment_value = 0.0
    active = 0
    for row in rows:
        kind = str(row.get("type") or row.get("product_type") or "unspecified").strip().lower() or "unspecified"
        by_type[kind] = by_type.get(kind, 0) + 1
        premium = _money(row.get("annual_premium", 0))
        premium_buckets[kind] = premium_buckets.get(kind, 0.0) + premium
        investment_value += _money(row.get("investment_value", 0))
        if _status(row) == "active":
            active += 1
            active_premium += premium
            coverage += _money(row.get("coverage_amount", 0))
    return {
        "total": len(rows),
        "active": active,
        "by_type": dict(sorted(by_type.items())),
        "annual_premium_active": _round2(active_premium),
        "annual_premium_by_type": {k: _round2(v) for k, v in sorted(premium_buckets.items())},
        "coverage_active": _round2(coverage),
        "investment_value": _round2(investment_value),
    }


def aggregate_health(policies: Mapping[str, Any], wallets: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = _as_list(wallets)
    balance_running = 0.0
    active = 0
    deposits = 0.0
    for row in rows:
        balance = _money(row.get("balance", 0))
        balance_running += balance
        if balance > 0:
            active += 1
        for tx in row.get("transactions") or []:
            if isinstance(tx, Mapping) and str(tx.get("type") or "") in {"deposit", "initial_deposit"}:
                deposits += _money(tx.get("amount", 0))
    by_type = policies.get("by_type") or {}
    premiums = policies.get("annual_premium_by_type") or {}
    return {
        "health_policies": int(by_type.get("health", 0)),
        "health_annual_premium": _round2(_money(premiums.get("health", 0))),
        "life_policies": int(by_type.get("life", 0)),
        "wallet_count": len(rows),
        "active_wallets": active,
        "wallet_balance": _round2(balance_running),
        "wallet_deposits": _round2(deposits),
    }


def aggregate_investments(
    accounts: Iterable[Mapping[str, Any]],
    policies: Mapping[str, Any],
    algo_balance: float = 0.0,
    pipeline_cash: float = 0.0,
) -> Dict[str, Any]:
    rows = _as_list(accounts)
    by_route: Dict[str, float] = {}
    running = 0.0
    for row in rows:
        route = str(row.get("investment_route") or row.get("route") or "unspecified").strip().lower() or "unspecified"
        balance = _money(row.get("balance", 0))
        by_route[route] = by_route.get(route, 0.0) + balance
        running += balance
    account_balance = _check_double_sum("investments.balance", running, by_route)
    policy_value = _round2(_money(policies.get("investment_value", 0)))
    health_placeholder = 0.0
    return {
        "account_count": len(rows),
        "account_balance": account_balance,
        "by_route": {k: _round2(v) for k, v in sorted(by_route.items())},
        "policy_investment_value": policy_value,
        "algo_balance": _round2(algo_balance),
        "pipeline_cash": _round2(pipeline_cash),
        "noted_health_placeholder": health_placeholder,
    }


def aggregate_agents(
    agents: Iterable[Mapping[str, Any]],
    commissions: Iterable[Mapping[str, Any]],
) -> Dict[str, Any]:
    agent_rows = _as_list(agents)
    comm_rows = _as_list(commissions)
    by_status = _count_status(agent_rows)
    rates = [_money(row.get("default_commission_rate", 0)) for row in agent_rows]
    amount_buckets: Dict[str, float] = {}
    running = 0.0
    for row in comm_rows:
        status = _status(row)
        amount = _money(row.get("amount", 0))
        amount_buckets[status] = amount_buckets.get(status, 0.0) + amount
        running += amount
    return {
        "agent_count": len(agent_rows),
        "agents_by_status": by_status,
        "active_agents": by_status.get("active", 0),
        "average_commission_rate": _round2(sum(rates) / len(rates)) if rates else 0.0,
        "commission_count": len(comm_rows),
        "commission_by_status": _count_status(comm_rows),
        "commission_amount": _check_double_sum("agents.commission", running, amount_buckets),
        "commission_amount_by_status": {k: _round2(v) for k, v in sorted(amount_buckets.items())},
    }


def _rate_rows(rows: Any) -> List[Dict[str, Any]]:
    cleaned = []
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        kept = {}
        for key in _RATE_FIELDS:
            if key in row and isinstance(row[key], (int, float)) and not isinstance(row[key], bool):
                kept[key] = row[key]
        if kept:
            cleaned.append(kept)
    return cleaned


def kernel_pricing_outline(store: Any) -> Dict[str, Any]:
    """Active version, published rate bands, and basic premiums from the kernel."""
    from services.pricing_kernel import (
        PricingCustomer,
        get_product,
        price_policy,
        pricing_config_from_underwriting,
        table_set_from_store,
    )

    current = str(getattr(store, "current_version", "") or "")
    tables = store.get_current_tables() if hasattr(store, "get_current_tables") else {}
    config = getattr(store, "config", None)
    config_version = str(getattr(config, "config_version", "") or "")
    versions = []
    catalog = store.versions if isinstance(getattr(store, "versions", None), dict) else {}
    for version_id, payload in catalog.items():
        payload = payload or {}
        integrity = ""
        if hasattr(store, "_version_integrity_hash"):
            integrity = store._version_integrity_hash(version_id)
        versions.append({
            "version": str(version_id),
            "status": payload.get("status"),
            "is_current": str(version_id) == current,
            "effective_date": payload.get("effective_date"),
            "parent_version": payload.get("parent_version"),
            "integrity_hash": integrity,
        })
    versions.sort(key=lambda item: (not item["is_current"], str(item["version"])))

    table_set = table_set_from_store(store)
    pricing_config = pricing_config_from_underwriting(config)
    product = get_product(REFERENCE_PRODUCT_ID)
    premiums = []
    for age in REFERENCE_AGES:
        priced = price_policy(
            PricingCustomer(
                age=int(age),
                coverage=REFERENCE_COVERAGE,
                term_years=REFERENCE_TERM_YEARS,
                adl_level=REFERENCE_ADL,
                smoking_status="nonsmoker",
            ),
            product,
            table_set,
            pricing_config,
        )
        if str(priced.tables_version) != current:
            raise RegulatorIntegrityError("kernel premium is not on the active tables version")
        if str(priced.config_version) != config_version:
            raise RegulatorIntegrityError("kernel premium is not on the active config version")
        premiums.append({
            "age": int(age),
            "coverage": REFERENCE_COVERAGE,
            "term_years": REFERENCE_TERM_YEARS,
            "adl_level": REFERENCE_ADL,
            "smoking_status": "nonsmoker",
            "annual_premium": _round2(priced.annual_premium),
            "monthly_premium": _round2(priced.monthly_premium),
            "risk_premium_annual": _round2(priced.risk_premium_annual),
            "savings_premium_annual": _round2(priced.savings_premium_annual),
            "expense_loading_annual": _round2(priced.expense_loading_annual),
            "profit_margin_annual": _round2(priced.profit_margin_annual),
            "eligible": bool(priced.eligible),
            "tables_version": str(priced.tables_version),
            "config_version": str(priced.config_version),
        })

    current_payload = catalog.get(current) or {}
    loadings = getattr(config, "loadings", None) or {}
    limits = getattr(config, "coverage_limits", None) or {}
    return {
        "current_version": current,
        "config_version": config_version,
        "state_revision": int(getattr(store, "state_revision", 0) or 0),
        "status": current_payload.get("status"),
        "effective_date": current_payload.get("effective_date"),
        "versions": versions,
        "rate_bands": {
            "mortality_rates": _rate_rows(tables.get("mortality_rates")),
            "disability_incidence_rates": _rate_rows(tables.get("disability_incidence_rates")),
            "lapse_rates": _rate_rows(tables.get("lapse_rates")),
        },
        "rules_in_force": {
            "decline_threshold": getattr(config, "decline_threshold", None),
            "expense_loading_pct": getattr(config, "expense_loading_pct", None),
            "profit_margin_pct": getattr(config, "profit_margin_pct", None),
            "discount_rate": getattr(config, "discount_rate", None),
            "loadings": {str(k): float(v) for k, v in dict(loadings).items()},
            "coverage_limits": {str(k): float(v) for k, v in dict(limits).items()},
        },
        "basic_premiums": {
            "product_id": product.id,
            "profile": "published_standard_nonsmoker",
            "coverage": REFERENCE_COVERAGE,
            "term_years": REFERENCE_TERM_YEARS,
            "adl_level": REFERENCE_ADL,
            "rows": premiums,
        },
    }


def _reconcile(outline: Mapping[str, Any], canonical: Mapping[str, Any]) -> None:
    checks = (
        ("claims", "disbursed_amount", "claims_disbursed_amount"),
        ("claims", "paid_amount", "claims_paid_amount"),
        ("claims", "pending_liability", "pending_claims_liability"),
        ("claims", "total", "total_claims"),
        ("policies", "total", "total_policies"),
        ("policies", "active", "active_policies"),
        ("policies", "annual_premium_active", "total_revenue"),
        ("policies", "coverage_active", "total_coverage_amount"),
        ("policies", "investment_value", "total_investment_value"),
        ("underwriting", "total", "total_applications"),
        ("underwriting", "pending", "pending_applications"),
        ("underwriting", "approved", "approved_applications"),
        ("underwriting", "rejected", "rejected_applications"),
    )
    for section, field, source in checks:
        if source not in canonical or canonical[source] is None:
            continue
        actual = outline[section][field]
        expected = canonical[source]
        if isinstance(actual, float) or isinstance(expected, float):
            if abs(_money(actual) - _money(expected)) > 0.02:
                raise RegulatorIntegrityError(f"{section}.{field} diverges from canonical books")
        elif actual != expected:
            raise RegulatorIntegrityError(f"{section}.{field} diverges from canonical books")


def assert_outline_clean(payload: Any, path: str = "$") -> None:
    """Reject an outline that still carries an identifier or a secret."""
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            lowered = str(key).lower()
            if any(part in lowered for part in _FORBIDDEN_KEY_PARTS):
                raise RegulatorIntegrityError(f"forbidden field at {path}.{key}")
            assert_outline_clean(value, f"{path}.{key}")
        return
    if isinstance(payload, list):
        for index, value in enumerate(payload):
            assert_outline_clean(value, f"{path}[{index}]")
        return
    if isinstance(payload, str):
        if _EMAIL_RE.search(payload) or _ID_RE.search(payload) or _SECRET_VALUE_RE.search(payload):
            raise RegulatorIntegrityError(f"forbidden value at {path}")


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def build_regulator_outline(
    *,
    actuarial_store: Any,
    policies: Optional[Iterable[Mapping[str, Any]]] = None,
    claims: Optional[Iterable[Mapping[str, Any]]] = None,
    underwriting: Optional[Iterable[Mapping[str, Any]]] = None,
    health_wallets: Optional[Iterable[Mapping[str, Any]]] = None,
    investment_accounts: Optional[Iterable[Mapping[str, Any]]] = None,
    agents: Optional[Iterable[Mapping[str, Any]]] = None,
    commissions: Optional[Iterable[Mapping[str, Any]]] = None,
    algo_balance: float = 0.0,
    pipeline_cash: float = 0.0,
    canonical: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return the redacted regulation outline for the supplied books.

    ``canonical`` is the executive metric snapshot (same formulas as
    ``compute_unified_financial_metrics``). When present, overlapping totals
    must match or the outline is refused.
    """
    policy_totals = aggregate_policies(policies or [])
    claim_totals = aggregate_claims(claims or [])
    underwriting_totals = aggregate_underwriting(underwriting or [])
    health = aggregate_health(policy_totals, health_wallets or [])
    investments = aggregate_investments(
        investment_accounts or [],
        policy_totals,
        algo_balance=algo_balance,
        pipeline_cash=pipeline_cash,
    )
    investments.pop("noted_health_placeholder", None)
    agent_totals = aggregate_agents(agents or [], commissions or [])
    pricing = kernel_pricing_outline(actuarial_store)

    wallet_balance = health["wallet_balance"]
    aum = _round2(
        policy_totals["investment_value"]
        + wallet_balance
        + investments["account_balance"]
        + investments["algo_balance"]
        + investments["pipeline_cash"]
    )
    investments["assets_under_management"] = aum

    premium = policy_totals["annual_premium_active"]
    loss_ratio = _round2(claim_totals["disbursed_amount"] / premium) if premium else 0.0

    outline: Dict[str, Any] = {
        "view": "regulator_outline",
        "access": "read_only",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "pricing": pricing,
        "underwriting": underwriting_totals,
        "claims": claim_totals,
        "claims_loss_ratio": loss_ratio,
        "investments": investments,
        "health": health,
        "agents": agent_totals,
        "policies": {
            "total": policy_totals["total"],
            "active": policy_totals["active"],
            "by_type": policy_totals["by_type"],
            "annual_premium_active": policy_totals["annual_premium_active"],
            "coverage_active": policy_totals["coverage_active"],
            "investment_value": policy_totals["investment_value"],
        },
    }
    if canonical:
        _reconcile(outline, canonical)
    assert_outline_clean(outline)
    digest = _canonical_hash(outline)
    outline["integrity"] = {
        "outline_sha256": digest,
        "reconciled": canonical is not None,
        "source_counts": {
            "policies": policy_totals["total"],
            "claims": claim_totals["total"],
            "underwriting": underwriting_totals["total"],
            "health_wallets": health["wallet_count"],
            "investment_accounts": investments["account_count"],
            "agents": agent_totals["agent_count"],
            "commissions": agent_totals["commission_count"],
        },
        "tables_version": pricing["current_version"],
        "config_version": pricing["config_version"],
    }
    # The hash covers the book, not itself. Re-check the sealed copy still
    # has no secrets, then confirm the sealed hash matches a fresh digest of
    # the pre-integrity body.
    assert_outline_clean(outline)
    sealed = dict(outline)
    sealed.pop("integrity")
    if _canonical_hash(sealed) != digest:
        raise RegulatorIntegrityError("outline hash does not match the sealed book")
    return outline
