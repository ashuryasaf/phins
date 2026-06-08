"""
Mislaka Affiliation Engine
==========================
Rebuilds the Mislaka projection around **affiliations** - the authoritative
Mislaka schema mappings (interface / product / status / entity / id-type
codes) defined in :class:`services.pension_data_agent.MislakaSchemaMapping`
and the insurance-company codes in
:class:`services.mislaka_api_service.MislakaAPIService`.

Design rules (data integrity is non-negotiable):

* **No mock / demo / sample data.** Every value here is derived from the
  clearinghouse response that is passed in. If a code cannot be decoded the
  raw code is preserved verbatim and flagged ``decoded=False`` - nothing is
  invented.
* **Deterministic.** The same input always yields the same output, so the
  SHA-256 integrity envelope is stable and reproducible.
* **Filter, never fabricate.** Adjustable reporting narrows the *real* fact
  set (by policy number, product, status, provider, or date window). Records
  are only ever removed by an explicit filter, never added.

The engine is a pure projection layer: it decodes and groups facts but does
not compute risk scores or statistical "analysis". Risk scoring and chart
synthesis remain the Assessment Center's responsibility.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple


# ── Affiliation source-of-truth accessors ──────────────────────────────────

def _schema_mapping():
    """Return the authoritative Mislaka schema mapping class.

    Imported lazily so this module stays import-cheap and avoids any circular
    import with the (large) pension data agent module.
    """
    from services.pension_data_agent import MislakaSchemaMapping
    return MislakaSchemaMapping


def _company_codes() -> Dict[str, str]:
    """Return the authoritative insurance-company (provider) code map."""
    from services.mislaka_api_service import MislakaAPIService
    return dict(MislakaAPIService.COMPANY_CODES)


# ── Tolerant field + date helpers ───────────────────────────────────────────

def _get(policy: Any, *names: str, default: Any = None) -> Any:
    """Read an attribute or dict key from a policy-like object.

    Works for both :class:`MislakaPolicy` dataclasses and the plain dict fact
    rows emitted by :func:`services.mislaka_report_generator.mislaka_facts`.
    """
    for name in names:
        if isinstance(policy, dict):
            if name in policy and policy[name] not in (None, ""):
                return policy[name]
        else:
            val = getattr(policy, name, None)
            if val not in (None, ""):
                return val
    return default


def _parse_date(value: Any) -> Optional[date]:
    """Parse a Mislaka-style date into a ``date`` or ``None``.

    Tolerant of the formats the clearinghouse and uploaded files use
    (``YYYY-MM-DD``, ``YYYYMMDD``, ``DD/MM/YYYY``, ISO timestamps). Returns
    ``None`` when the value cannot be parsed - callers must decide what an
    undated record means; this helper never guesses a date.
    """
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    if not raw:
        return None

    # ISO timestamp first (handles trailing Z / time component).
    iso_candidate = raw.replace("Z", "").split("T")[0].split(" ")[0]
    fmts = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d")
    for fmt in fmts:
        try:
            return datetime.strptime(iso_candidate, fmt).date()
        except (ValueError, TypeError):
            continue

    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 8:
        # Could be YYYYMMDD or DDMMYYYY - prefer YYYYMMDD (clearinghouse norm).
        for fmt in ("%Y%m%d", "%d%m%Y"):
            try:
                return datetime.strptime(digits, fmt).date()
            except (ValueError, TypeError):
                continue
    return None


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


# ── Adjustable report filters ───────────────────────────────────────────────

@dataclass
class ReportFilters:
    """Adjustable reporting controls.

    Every field is optional; an unset field imposes no constraint. Matching is
    inclusive and case-insensitive for textual fields. A value may be supplied
    either as the raw Mislaka code (e.g. status ``"1"``) or the decoded name
    (e.g. ``"active"``) - both match.
    """

    policy_number: Optional[str] = None
    product_type: Optional[str] = None
    status: Optional[str] = None
    company_code: Optional[str] = None
    provider: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    # Which policy date the window applies to: "start_date" (default) or
    # "last_update".
    date_field: str = "start_date"

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ReportFilters":
        data = data or {}

        def pick(*keys: str) -> Optional[str]:
            for key in keys:
                val = data.get(key)
                if val not in (None, ""):
                    return str(val).strip()
            return None

        date_field = pick("date_field") or "start_date"
        if date_field not in ("start_date", "last_update"):
            date_field = "start_date"

        return cls(
            policy_number=pick("policy_number", "policyNumber", "policy_no"),
            product_type=pick("product_type", "productType"),
            status=pick("status"),
            company_code=pick("company_code", "companyCode", "provider_code"),
            provider=pick("provider", "company_name", "companyName"),
            date_from=pick("date_from", "dateFrom", "from_date", "start"),
            date_to=pick("date_to", "dateTo", "to_date", "end"),
            date_field=date_field,
        )

    def is_active(self) -> bool:
        return any([
            self.policy_number, self.product_type, self.status,
            self.company_code, self.provider, self.date_from, self.date_to,
        ])

    def to_dict(self) -> Dict[str, Any]:
        out = {
            "policy_number": self.policy_number,
            "product_type": self.product_type,
            "status": self.status,
            "company_code": self.company_code,
            "provider": self.provider,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "date_field": self.date_field,
        }
        return {k: v for k, v in out.items() if v not in (None, "")}


# ── Affiliation decoding ────────────────────────────────────────────────────

def decode_affiliations(policy: Any) -> Dict[str, Any]:
    """Decode a policy's raw codes into named affiliations.

    Returns a structured ``affiliations`` block. Each decoded dimension keeps
    the raw code AND the resolved name(s); when a code is unknown the raw
    value is preserved and ``decoded`` is ``False`` so dashboards never show a
    fabricated label.
    """
    mapping = _schema_mapping()
    companies = _company_codes()

    affiliations: Dict[str, Any] = {}

    # Product affiliation (SUG-MUTZAR).
    raw_product = _get(policy, "product_type", "product_type_code", default="")
    product_entry = mapping.PRODUCT_TYPE_CODES.get(str(raw_product).strip())
    affiliations["product"] = {
        "code": str(raw_product).strip(),
        "name": (product_entry or {}).get("en", str(raw_product).strip()),
        "name_he": (product_entry or {}).get("he", ""),
        "key": (product_entry or {}).get("name", ""),
        "decoded": bool(product_entry),
    }

    # Status affiliation (STATUS-POLISA-O-CHESHBON).
    raw_status = _get(policy, "status", default="")
    status_entry = mapping.STATUS_CODES.get(str(raw_status).strip())
    affiliations["status"] = {
        "code": str(raw_status).strip(),
        "name": (status_entry or {}).get("en", str(raw_status).strip()),
        "name_he": (status_entry or {}).get("he", ""),
        "key": (status_entry or {}).get("name", ""),
        "decoded": bool(status_entry),
    }

    # Provider affiliation (YeshutYatzran).
    raw_company_code = str(_get(policy, "company_code", "provider_code", default="")).strip()
    raw_company_name = str(_get(policy, "company_name", "provider", default="")).strip()
    resolved_name = raw_company_name or companies.get(raw_company_code, "")
    affiliations["provider"] = {
        "code": raw_company_code,
        "name": resolved_name or raw_company_code,
        "decoded": bool(resolved_name),
    }

    # Interface affiliation (SUG-MIMSHAK) - present only when the upstream
    # payload carried it (e.g. file ingestion). Mislaka API rows usually omit
    # it, in which case we surface it as not-decoded rather than guessing.
    raw_interface = _get(policy, "interface_code", "interface", default="")
    interface_entry = None
    if str(raw_interface).strip():
        try:
            interface_entry = mapping.INTERFACE_CODES.get(int(raw_interface))
        except (ValueError, TypeError):
            interface_entry = None
    affiliations["interface"] = {
        "code": str(raw_interface).strip(),
        "name": (interface_entry or {}).get("name", str(raw_interface).strip()),
        "name_he": (interface_entry or {}).get("he", ""),
        "decoded": bool(interface_entry),
    }

    return affiliations


def enrich_policy(policy: Any) -> Dict[str, Any]:
    """Project a policy into a flat, affiliation-enriched fact row."""
    affiliations = decode_affiliations(policy)
    return {
        "policy_id": _get(policy, "policy_id", "id", default=""),
        "policy_number": _get(policy, "policy_number", default=""),
        "product_type": _get(policy, "product_type", default=""),
        "company_code": _get(policy, "company_code", "provider_code", default=""),
        "company_name": _get(policy, "company_name", "provider", default=""),
        "status": _get(policy, "status", default=""),
        "start_date": _get(policy, "start_date", default=""),
        "last_update": _get(policy, "last_update", default=""),
        "premium_monthly": _get(policy, "premium_monthly", "monthly_premium", default=None),
        "cover_amount": _get(policy, "cover_amount", "coverage_amount", default=None),
        "accumulated_value": _get(policy, "accumulated_value", "total_balance", default=None),
        "management_fee_percent": _get(policy, "management_fee_percent", default=None),
        "investment_track": _get(policy, "investment_track", default=""),
        # Affiliation block + convenient flattened labels for tables.
        "affiliations": affiliations,
        "affiliation_product": affiliations["product"]["name"],
        "affiliation_status": affiliations["status"]["name"],
        "affiliation_provider": affiliations["provider"]["name"],
    }


# ── Filtering ───────────────────────────────────────────────────────────────

def policy_matches(policy: Any, filters: ReportFilters) -> bool:
    """Return ``True`` when a policy satisfies every active filter."""
    if not filters.is_active():
        return True

    affiliations = decode_affiliations(policy)

    if filters.policy_number:
        if _norm(filters.policy_number) != _norm(_get(policy, "policy_number")):
            return False

    if filters.product_type:
        want = _norm(filters.product_type)
        prod = affiliations["product"]
        candidates = {_norm(prod["code"]), _norm(prod["name"]), _norm(prod["key"])}
        if want not in candidates:
            return False

    if filters.status:
        want = _norm(filters.status)
        st = affiliations["status"]
        candidates = {_norm(st["code"]), _norm(st["name"]), _norm(st["key"])}
        if want not in candidates:
            return False

    if filters.company_code:
        if _norm(filters.company_code) != _norm(_get(policy, "company_code", "provider_code")):
            return False

    if filters.provider:
        prov_name = _norm(affiliations["provider"]["name"])
        if _norm(filters.provider) not in prov_name:
            return False

    if filters.date_from or filters.date_to:
        policy_date = _parse_date(_get(policy, filters.date_field))
        # An undated record cannot be confirmed inside an explicit window, so a
        # date filter excludes it. We never fabricate a date to keep it.
        if policy_date is None:
            return False
        if filters.date_from:
            start = _parse_date(filters.date_from)
            if start and policy_date < start:
                return False
        if filters.date_to:
            end = _parse_date(filters.date_to)
            if end and policy_date > end:
                return False

    return True


def apply_filters(policies: List[Any], filters: ReportFilters) -> List[Any]:
    """Return the subset of ``policies`` matching ``filters`` (order preserved)."""
    return [p for p in policies if policy_matches(p, filters)]


# ── Grouping (A-Z structural projection) ────────────────────────────────────

def _group_by(rows: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    """Group enriched rows by an affiliation label, sorted A-Z.

    This is a structural projection (which policies share an affiliation), not
    statistical analysis - it lists membership, it does not score anything.
    """
    buckets: Dict[str, List[str]] = {}
    for row in rows:
        label = str(row.get(key) or "(unspecified)")
        buckets.setdefault(label, []).append(str(row.get("policy_number") or row.get("policy_id") or ""))
    return [
        {"affiliation": label, "policy_count": len(members), "policies": members}
        for label, members in sorted(buckets.items(), key=lambda kv: kv[0].lower())
    ]


def build_affiliation_projection(
    policies: List[Any],
    *,
    filters: Optional[ReportFilters] = None,
) -> Dict[str, Any]:
    """Build the full affiliation projection for a set of policies.

    Returns a deterministic dict with:

    * ``rows`` - every (filtered) policy, affiliation-enriched, sorted A-Z by
      provider then policy number for stable output;
    * ``groups`` - membership grouped by product / status / provider
      affiliation;
    * ``filters`` - the active filter set (echoed back for the report header);
    * ``source_policy_count`` / ``policy_count`` - counts before/after filter;
    * ``integrity`` - a SHA-256 envelope over the projected rows.
    """
    filters = filters or ReportFilters()
    source_count = len(policies)
    selected = apply_filters(policies, filters)
    rows = [enrich_policy(p) for p in selected]
    rows.sort(key=lambda r: (str(r.get("affiliation_provider")).lower(),
                             str(r.get("policy_number")).lower()))

    return {
        "rows": rows,
        "groups": {
            "by_product": _group_by(rows, "affiliation_product"),
            "by_status": _group_by(rows, "affiliation_status"),
            "by_provider": _group_by(rows, "affiliation_provider"),
        },
        "filters": filters.to_dict(),
        "filters_active": filters.is_active(),
        "source_policy_count": source_count,
        "policy_count": len(rows),
        "integrity": integrity_envelope(rows),
    }


# ── Integrity envelope ──────────────────────────────────────────────────────

def integrity_envelope(rows: List[Dict[str, Any]]) -> Dict[str, str]:
    """Return a deterministic SHA-256 envelope over projected rows."""
    payload = json.dumps(rows, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return {"sha256": digest, "row_count": str(len(rows))}


def affiliation_catalog() -> Dict[str, Any]:
    """Return the full A-Z affiliation catalog (every code -> name).

    Mirrors ``GET /api/mislaka/affiliations`` but is importable so reports and
    tests can render the authoritative legend without an HTTP round-trip.
    """
    mapping = _schema_mapping()
    return {
        "interface_codes": mapping.INTERFACE_CODES,
        "product_types": mapping.PRODUCT_TYPE_CODES,
        "entity_types": mapping.ENTITY_TYPE_CODES,
        "status_codes": mapping.STATUS_CODES,
        "id_types": mapping.ID_TYPE_CODES,
        "environment_codes": mapping.ENVIRONMENT_CODES,
        "company_codes": _company_codes(),
    }
