"""ADL 3 premium release cost: a read-only actuarial test.

The ADL 3 disabled life expectancy table gives the remaining years after an
ADL 3 event, by age and sex. The test assumes the premium is released for
those years:

    release cost = released years x annual premium

``released years`` is the table's remaining years at the attained age for the
recorded sex (the published average when the sex is not recorded). With a
premium payment term, the release covers only the years a premium is still
due: ``min(remaining years, payment term - years already paid)``.

The release cost is the amount to hedge for that policy. The projection
weights it by the active mortality and disability incidence tables to give
the expected cost by year and the adjusted disability exposure.

Nothing here writes a policy, a premium, a bill, a kernel pin, or a ledger
row. A missing age, premium, or table row is withheld and listed, never
filled in. The issued contract still charges the premium after a disability
(``post_disability_premium_factor``); this is an assumption test beside it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from services.adl3_disabled_life_expectancy import (
    AGE_MAX,
    AGE_MIN,
    TABLE_NAME,
    adl3_row_at,
    adl3_rows_for_tables,
)

TEST_ID = "adl3_premium_release_cost"
METHOD_VERSION = "1"

PREMIUM_PAYMENT_YEARS_MIN = 1
PREMIUM_PAYMENT_YEARS_MAX = 110
PROJECTION_YEARS_MIN = 1
PROJECTION_YEARS_MAX = 60
PROJECTION_YEARS_DEFAULT = 30
DEFAULT_REFERENCE_PREMIUM = Decimal("1000.00")
MAX_CASE_PREMIUM = Decimal("100000000")
REFERENCE_AGES = tuple(range(20, 90, 5))
MAX_LISTED_ROWS = 500

IN_FORCE_STATUSES = frozenset({"active", "in_force", "issued", "approved"})

_CENT = Decimal("0.01")
_ZERO = Decimal("0")
_MALE = frozenset({"male", "m", "man", "זכר"})
_FEMALE = frozenset({"female", "f", "woman", "נקבה"})
_SEX_COLUMN = {"male": "male_years", "female": "female_years", "average": "average_years"}

BASIS_NOTE = (
    "Assumption test. Release cost is the ADL 3 remaining years for the attained "
    "age and sex, times the policy's annual premium. No premium, bill, cover, "
    "kernel pin, or ledger row is changed."
)
PROJECTION_NOTE = (
    "Each year uses the attained age that year: the table's remaining years, the "
    "mortality q(x) and the disability incidence i(x) of the active tables, death "
    "before disability, no lapse. ADL and demographic multipliers are not applied. "
    "A year whose rate is missing ends that policy's projection and is named."
)


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _parse_int(value: Any, name: str, low: int, high: int) -> int:
    text = str(value).strip()
    if not text.lstrip("+").isdigit():
        raise ValueError(f"{name} must be a whole number between {low} and {high}")
    number = int(text)
    if not low <= number <= high:
        raise ValueError(f"{name} must be a whole number between {low} and {high}")
    return number


def parse_premium_payment_years(value: Any) -> Optional[int]:
    """Blank means the whole table expectancy is released."""
    if _blank(value):
        return None
    return _parse_int(value, "premium_payment_years",
                      PREMIUM_PAYMENT_YEARS_MIN, PREMIUM_PAYMENT_YEARS_MAX)


def parse_projection_years(value: Any) -> int:
    if _blank(value):
        return PROJECTION_YEARS_DEFAULT
    return _parse_int(value, "projection_years", PROJECTION_YEARS_MIN, PROJECTION_YEARS_MAX)


def parse_reference_premium(value: Any) -> Optional[Decimal]:
    """Annual premium the reference grid is shown for. Blank uses the book average."""
    if _blank(value):
        return None
    premium = _money(value)
    if premium is None or premium <= 0 or premium > MAX_CASE_PREMIUM:
        raise ValueError("reference_annual_premium must be a positive amount")
    return premium


def parse_case(age: Any, sex: Any, annual_premium: Any, years_paid: Any) -> Optional[Dict[str, Any]]:
    """Inputs of the single-case calculator. All blank means no case was asked."""
    if all(_blank(item) for item in (age, sex, annual_premium, years_paid)):
        return None
    if _blank(age) or _blank(annual_premium):
        raise ValueError("case_age and case_annual_premium are both required for a case")
    case_age = _parse_int(age, "case_age", AGE_MIN, AGE_MAX)
    premium = _money(annual_premium)
    if premium is None or premium <= 0 or premium > MAX_CASE_PREMIUM:
        raise ValueError("case_annual_premium must be a positive amount")
    sex_text = "" if _blank(sex) else str(sex).strip().lower()
    if sex_text in ("", "average", "unknown"):
        sex_used = "average"
    else:
        sex_used = normalize_sex(sex_text) or ""
        if not sex_used:
            raise ValueError("case_sex must be male, female, or average")
    paid = 0 if _blank(years_paid) else _parse_int(years_paid, "case_years_paid", 0, PREMIUM_PAYMENT_YEARS_MAX)
    return {"age": case_age, "sex": sex_used, "annual_premium": premium, "years_paid": paid}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _money(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite():
        return None
    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)


def _cents(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _f(value: Optional[Decimal]) -> Optional[float]:
    return None if value is None else float(value)


def _years(value: float) -> float:
    return round(float(value), 6)


def _sha(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_sex(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    if text in _MALE:
        return "male"
    if text in _FEMALE:
        return "female"
    return None


def _parse_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:10]).date()
    except (TypeError, ValueError):
        return None


def _full_years_between(start: Optional[date], end: date) -> Optional[int]:
    if start is None:
        return None
    if start > end:
        return 0
    years = end.year - start.year - ((end.month, end.day) < (start.month, start.day))
    return max(0, years)


def _int_or_none(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return int(number)


def _status(policy: Mapping[str, Any]) -> str:
    return str(policy.get("status") or "").strip().lower()


def _rate_per_life(table: Sequence[Mapping[str, Any]], age: int) -> Optional[float]:
    """Bracket rule of the active rate tables. An age with no bracket is None."""
    for bracket in table or []:
        if not isinstance(bracket, Mapping):
            continue
        try:
            low = int(bracket.get("age_min", 0))
            high = int(bracket.get("age_max", 0))
            rate = float(bracket.get("rate_per_1000")) / 1000.0
        except (TypeError, ValueError):
            continue
        if low <= int(age) < high:
            if rate < 0.0 or rate > 1.0:
                return None
            return rate
    return None


class _Basis:
    """The tables one run reads. Built once, never mutated."""

    def __init__(self, tables: Mapping[str, Any], tables_version: str, discount_rate: float,
                 premium_payment_years: Optional[int], projection_years: int, as_of: date) -> None:
        self.tables_version = str(tables_version or "")
        self.rows = adl3_rows_for_tables(dict(tables or {}))
        self._row_cache: Dict[int, Optional[Dict[str, Any]]] = {}
        self.mortality = list((tables or {}).get("mortality_rates") or [])
        self.incidence = list((tables or {}).get("disability_incidence_rates") or [])
        try:
            rate = float(discount_rate)
        except (TypeError, ValueError):
            rate = 0.0
        self.discount_rate = rate if 0.0 <= rate < 1.0 else 0.0
        self.premium_payment_years = premium_payment_years
        self.projection_years = int(projection_years)
        self.as_of = as_of
        self.table_hash = expectancy_table_hash(self.rows, self.tables_version)

    def row(self, age: int) -> Optional[Dict[str, Any]]:
        if age not in self._row_cache:
            self._row_cache[age] = adl3_row_at(self.rows, age) if AGE_MIN <= age <= AGE_MAX else None
        return self._row_cache[age]

    def expectancy(self, age: int, sex_used: str) -> Optional[float]:
        row = self.row(age)
        if row is None:
            return None
        try:
            value = float(row[_SEX_COLUMN[sex_used]])
        except (KeyError, TypeError, ValueError):
            return None
        if value != value or value < 0.0:
            return None
        return value

    def parameters(self) -> Dict[str, Any]:
        return {
            "premium_payment_years": self.premium_payment_years,
            "payment_basis": (
                "whole_expectancy" if self.premium_payment_years is None else "premium_payment_term"
            ),
            "projection_years": self.projection_years,
            "discount_rate": round(self.discount_rate, 6),
            "as_of": self.as_of.isoformat(),
        }


def expectancy_table_hash(rows: List[Dict[str, Any]], tables_version: str) -> str:
    """Same fingerprint the rate-table registry shows for the ADL 3 table."""
    from services.actuarial_service import _hash_table_rows

    return _hash_table_rows(rows, {
        "scope": "global",
        "table_type": TABLE_NAME,
        "tables_version": tables_version,
        "assumption_only": True,
    })


def load_actuarial_basis() -> Tuple[Dict[str, Any], str, float]:
    """Active tables, their version, and the pricing discount rate."""
    from services.actuarial_service import get_actuarial_store

    store = get_actuarial_store()
    tables = dict(store.get_current_tables() or {})
    version = str(getattr(store, "current_version", "") or "")
    try:
        discount_rate = float(getattr(store.config, "discount_rate", 0.0))
    except (TypeError, ValueError):
        discount_rate = 0.0
    return tables, version, discount_rate


# ---------------------------------------------------------------------------
# One case
# ---------------------------------------------------------------------------

def _released_years(basis: _Basis, age: int, sex_used: str, years_paid: int) -> Optional[Dict[str, Any]]:
    """Years of premium released at one attained age. None when the row is missing."""
    expectancy = basis.expectancy(age, sex_used)
    if expectancy is None:
        return None
    remaining: Optional[int] = None
    released = expectancy
    if basis.premium_payment_years is not None:
        remaining = max(0, basis.premium_payment_years - int(years_paid))
        released = min(expectancy, float(remaining))
    return {
        "expectancy_years": _years(expectancy),
        "remaining_payment_years": remaining,
        "released_years": _years(released),
    }


def _release_cost(released_years: float, annual_premium: Decimal) -> Decimal:
    return _cents(Decimal(str(_years(released_years))) * annual_premium)


def _project(basis: _Basis, age: int, sex_used: str, annual_premium: Decimal,
             years_paid: int) -> Dict[str, Any]:
    """Expected release cost by year from the active q(x) and i(x)."""
    rows: List[Dict[str, Any]] = []
    stopped: Optional[Dict[str, Any]] = None
    in_force = 1.0
    expected_total = _ZERO
    pv_total = _ZERO
    for offset in range(basis.projection_years):
        attained = age + offset
        paid = years_paid + offset
        if basis.premium_payment_years is not None and paid >= basis.premium_payment_years:
            break
        if attained > AGE_MAX:
            stopped = {"age": attained, "reason": "age_above_table"}
            break
        release = _released_years(basis, attained, sex_used, paid)
        if release is None:
            stopped = {"age": attained, "reason": "no_expectancy_row"}
            break
        qx = _rate_per_life(basis.mortality, attained)
        if qx is None:
            stopped = {"age": attained, "reason": "no_mortality_rate"}
            break
        ix = _rate_per_life(basis.incidence, attained)
        if ix is None:
            stopped = {"age": attained, "reason": "no_disability_incidence_rate"}
            break
        cost = _release_cost(release["released_years"], annual_premium)
        probability = round(in_force * (1.0 - qx) * ix, 10)
        expected = _cents(cost * Decimal(repr(probability)))
        discount = (1.0 + basis.discount_rate) ** (-(offset + 1))
        discounted = _cents(expected * Decimal(repr(discount)))
        rows.append({
            "year": offset + 1,
            "calendar_year": basis.as_of.year + offset,
            "attained_age": attained,
            "expectancy_years": release["expectancy_years"],
            "released_years": release["released_years"],
            "release_cost": float(cost),
            "mortality_qx": round(qx, 6),
            "disability_incidence_ix": round(ix, 6),
            "in_force_probability": round(in_force, 8),
            "event_probability": probability,
            "expected_release_cost": float(expected),
            "discounted_expected_release_cost": float(discounted),
        })
        expected_total += expected
        pv_total += discounted
        in_force = in_force * (1.0 - qx) * (1.0 - ix)
    return {
        "rows": rows,
        "stopped": stopped,
        "expected_total": expected_total,
        "pv_total": pv_total,
    }


def release_case(basis: _Basis, *, age: int, sex_used: str, annual_premium: Decimal,
                 years_paid: int) -> Dict[str, Any]:
    """One life, one premium. ``status`` is ``assessed`` or ``withheld``."""
    result: Dict[str, Any] = {
        "status": "withheld",
        "reason": "",
        "attained_age": int(age),
        "sex_used": sex_used,
        "annual_premium": float(annual_premium),
        "years_paid": int(years_paid),
        "premium_payment_years": basis.premium_payment_years,
    }
    if not AGE_MIN <= int(age) <= AGE_MAX:
        result["reason"] = "age_outside_table"
        return result
    release = _released_years(basis, int(age), sex_used, int(years_paid))
    if release is None:
        result["reason"] = "no_expectancy_row"
        return result
    cost = _release_cost(release["released_years"], annual_premium)
    projection = _project(basis, int(age), sex_used, annual_premium, int(years_paid))
    first = projection["rows"][0] if projection["rows"] else None
    expected_year1 = None if first is None else Decimal(str(first["expected_release_cost"]))
    result.update({
        "status": "assessed",
        "reason": "",
        "expectancy_years": release["expectancy_years"],
        "remaining_payment_years": release["remaining_payment_years"],
        "released_years": release["released_years"],
        "release_cost": float(cost),
        "mortality_qx": None if first is None else first["mortality_qx"],
        "disability_incidence_ix": None if first is None else first["disability_incidence_ix"],
        "expected_release_cost_year1": _f(expected_year1),
        "hedge_pct_of_annual_premium": (
            None if expected_year1 is None or annual_premium <= 0
            else round(float(expected_year1 / annual_premium * 100), 4)
        ),
        "expected_release_cost_projected": float(projection["expected_total"]),
        "expected_release_cost_pv": float(projection["pv_total"]),
        "projection_years_run": len(projection["rows"]),
        "projection_stopped": projection["stopped"],
        "projection": projection["rows"],
    })
    return result


# ---------------------------------------------------------------------------
# One policy
# ---------------------------------------------------------------------------

def _policy_id(policy: Mapping[str, Any], fallback: Any = "") -> str:
    return str(policy.get("id") or policy.get("policy_id") or fallback or "")


def _policy_start(policy: Mapping[str, Any]) -> Tuple[Optional[date], Optional[str]]:
    for key in ("start_date", "approval_date", "issuance_date", "created_date"):
        found = _parse_date(policy.get(key))
        if found is not None:
            return found, key
    return None, None


def _resolve_age(policy: Mapping[str, Any], application: Optional[Mapping[str, Any]],
                 customer: Optional[Mapping[str, Any]], as_of: date,
                 years_in_force: Optional[int]) -> Tuple[Optional[int], str]:
    """Attained age and where it came from. A date of birth is the master."""
    person = customer or {}
    born = _parse_date(person.get("dob") or person.get("date_of_birth"))
    if born is not None and born <= as_of:
        age = as_of.year - born.year - ((as_of.month, as_of.day) < (born.month, born.day))
        return age, "customer_date_of_birth"
    elapsed = years_in_force or 0
    for source, record in (("policy_issue_age", policy), ("application_age", application or {})):
        issue_age = _int_or_none(record.get("age"))
        if issue_age is not None and issue_age > 0:
            suffix = "_plus_years_in_force" if years_in_force is not None else "_start_date_missing"
            return issue_age + elapsed, source + suffix
    recorded = _int_or_none(person.get("age"))
    if recorded is not None and recorded > 0:
        return recorded, "customer_recorded_age"
    return None, "not_recorded"


def _resolve_sex(policy: Mapping[str, Any], application: Optional[Mapping[str, Any]],
                 customer: Optional[Mapping[str, Any]]) -> Tuple[str, str]:
    """``male``/``female`` when the record states one. A disagreement is not resolved."""
    stated: List[Tuple[str, str]] = []
    for source, record in (("customer", customer or {}), ("application", application or {}),
                           ("policy", policy)):
        sex = normalize_sex(record.get("gender") or record.get("sex"))
        if sex:
            stated.append((source, sex))
    if not stated:
        return "average", "average_sex_not_recorded"
    if len({sex for _source, sex in stated}) > 1:
        return "average", "average_records_disagree"
    return stated[0][1], stated[0][0] + "_record"


def _pinned_amount(policy: Mapping[str, Any], key: str) -> Tuple[Optional[Decimal], str]:
    """A kernel pin as issued. A missing pin or a broken seal is not estimated."""
    if policy.get("kernel_pin_intact") is False:
        return None, "pin_seal_broken"
    raw = policy.get(key)
    if raw is None or raw == "":
        return None, "not_pinned"
    amount = _money(raw)
    if amount is None or amount < 0:
        return None, "not_pinned"
    return amount, "kernel_pin"


def assess_policy(basis: _Basis, policy: Mapping[str, Any], *,
                  application: Optional[Mapping[str, Any]] = None,
                  customer: Optional[Mapping[str, Any]] = None,
                  policy_id: str = "") -> Dict[str, Any]:
    """Release cost and adjusted risk for one policy. Reads only."""
    pid = _policy_id(policy, policy_id)
    row: Dict[str, Any] = {
        "policy_id": pid,
        "customer_id": str(policy.get("customer_id") or ""),
        "policy_type": str(policy.get("type") or ""),
        "policy_status": _status(policy),
        "status": "withheld",
        "reason": "",
    }
    premium = _money(policy.get("annual_premium"))
    row["annual_premium"] = _f(premium)
    if premium is None or premium <= 0:
        row["reason"] = "no_annual_premium"
        return row

    start, start_source = _policy_start(policy)
    years_in_force = _full_years_between(start, basis.as_of)
    row["policy_start"] = None if start is None else start.isoformat()
    row["policy_start_source"] = start_source
    row["years_paid"] = years_in_force or 0
    row["years_paid_basis"] = "full_years_since_policy_start" if start is not None else "start_date_missing_counted_as_zero"

    age, age_source = _resolve_age(policy, application, customer, basis.as_of, years_in_force)
    sex_used, sex_basis = _resolve_sex(policy, application, customer)
    row["attained_age"] = age
    row["age_source"] = age_source
    row["sex_used"] = sex_used
    row["sex_basis"] = sex_basis
    if age is None:
        row["reason"] = "no_age_on_record"
        return row

    case = release_case(basis, age=age, sex_used=sex_used, annual_premium=premium,
                        years_paid=row["years_paid"])
    if case["status"] != "assessed":
        row["reason"] = case["reason"]
        return row
    for key in (
        "expectancy_years", "remaining_payment_years", "released_years", "release_cost",
        "mortality_qx", "disability_incidence_ix", "expected_release_cost_year1",
        "hedge_pct_of_annual_premium", "expected_release_cost_projected",
        "expected_release_cost_pv", "projection_years_run", "projection_stopped", "projection",
    ):
        row[key] = case[key]
    row["premium_payment_years"] = basis.premium_payment_years

    cost = Decimal(str(case["release_cost"]))
    expected_year1 = (
        None if case["expected_release_cost_year1"] is None
        else Decimal(str(case["expected_release_cost_year1"]))
    )

    # Premium view: the risk the kernel priced at issue, plus the expected release cost.
    disability_premium, premium_basis = _pinned_amount(policy, "disability_premium_annual")
    risk_premium, _risk_basis = _pinned_amount(policy, "risk_premium_annual")
    row["disability_premium_annual"] = _f(disability_premium)
    row["risk_premium_annual"] = _f(risk_premium)
    row["priced_risk_basis"] = premium_basis
    row["adjusted_disability_premium_annual"] = None
    row["disability_premium_uplift_pct"] = None
    row["adjusted_risk_premium_annual"] = None
    row["risk_premium_uplift_pct"] = None
    if expected_year1 is not None:
        if disability_premium is not None:
            row["adjusted_disability_premium_annual"] = float(disability_premium + expected_year1)
            if disability_premium > 0:
                row["disability_premium_uplift_pct"] = round(
                    float(expected_year1 / disability_premium * 100), 4)
        if risk_premium is not None:
            row["adjusted_risk_premium_annual"] = float(risk_premium + expected_year1)
            if risk_premium > 0:
                row["risk_premium_uplift_pct"] = round(float(expected_year1 / risk_premium * 100), 4)

    # Exposure view: the disability sum pinned at issue, plus the release cost.
    disability_sum, sum_basis = _pinned_amount(policy, "disability_sum_used")
    row["disability_sum"] = _f(disability_sum)
    row["disability_sum_basis"] = sum_basis
    row["adjusted_disability_exposure"] = None
    row["risk_uplift_pct"] = None
    row["expected_disability_claim_year1"] = None
    row["adjusted_expected_disability_year1"] = None
    if disability_sum is not None:
        row["adjusted_disability_exposure"] = float(disability_sum + cost)
        if disability_sum > 0:
            row["risk_uplift_pct"] = round(float(cost / disability_sum * 100), 4)
        first = case["projection"][0] if case["projection"] else None
        if first is not None and expected_year1 is not None:
            probability = Decimal(repr(first["event_probability"]))
            expected_claim = _cents(disability_sum * probability)
            row["expected_disability_claim_year1"] = float(expected_claim)
            row["adjusted_expected_disability_year1"] = float(expected_claim + expected_year1)
    row["status"] = "assessed"
    row["integrity_hash"] = _row_hash(basis, row)
    return row


_ROW_HASH_KEYS = (
    "policy_id", "customer_id", "annual_premium", "attained_age", "age_source", "sex_used",
    "sex_basis", "years_paid", "expectancy_years", "remaining_payment_years", "released_years",
    "release_cost", "expected_release_cost_year1", "expected_release_cost_projected",
    "expected_release_cost_pv", "disability_sum", "adjusted_disability_exposure",
    "disability_premium_annual", "risk_premium_annual", "adjusted_disability_premium_annual",
    "adjusted_risk_premium_annual",
)


def _row_hash(basis: _Basis, row: Mapping[str, Any]) -> str:
    return _sha({
        "test": TEST_ID,
        "method": METHOD_VERSION,
        "table": basis.table_hash,
        "parameters": basis.parameters(),
        "row": {key: row.get(key) for key in _ROW_HASH_KEYS},
    })


# ---------------------------------------------------------------------------
# The book
# ---------------------------------------------------------------------------

def _index_applications(applications: Any) -> Dict[str, Mapping[str, Any]]:
    index: Dict[str, Mapping[str, Any]] = {}
    try:
        items = list(applications.items()) if hasattr(applications, "items") else [
            (str((app or {}).get("id") or ""), app) for app in (applications or [])
        ]
    except Exception:
        return index
    for app_id, app in items:
        if not isinstance(app, Mapping):
            continue
        index[str(app_id)] = app
        if app.get("policy_id"):
            index.setdefault("policy:" + str(app.get("policy_id")), app)
    return index


def _policy_items(policies: Any) -> List[Tuple[str, Mapping[str, Any]]]:
    if hasattr(policies, "items"):
        raw = list(policies.items())
    else:
        raw = [(_policy_id(item), item) for item in (policies or []) if isinstance(item, Mapping)]
    items = [(str(key), value) for key, value in raw if isinstance(value, Mapping)]
    items.sort(key=lambda pair: _policy_id(pair[1], pair[0]))
    return items


def _customer_name(customer: Optional[Mapping[str, Any]]) -> str:
    if not isinstance(customer, Mapping):
        return ""
    name = str(customer.get("name") or "").strip()
    if name:
        return name
    return " ".join(
        part for part in (str(customer.get("first_name") or "").strip(),
                          str(customer.get("last_name") or "").strip()) if part
    )


def _age_band(age: int) -> str:
    low = (int(age) // 10) * 10
    return f"{low}-{low + 9}"


def _sum(rows: Iterable[Mapping[str, Any]], key: str) -> Decimal:
    total = _ZERO
    for row in rows:
        value = row.get(key)
        if value is not None:
            total += Decimal(str(value))
    return _cents(total)


def _reference_grid(basis: _Basis, premium: Decimal) -> List[Dict[str, Any]]:
    grid = []
    for age in REFERENCE_AGES:
        entry: Dict[str, Any] = {"age": age}
        for sex_used in ("male", "female", "average"):
            release = _released_years(basis, age, sex_used, 0)
            entry[f"{sex_used}_years"] = None if release is None else release["expectancy_years"]
            entry[f"{sex_used}_released_years"] = None if release is None else release["released_years"]
            entry[f"{sex_used}_release_cost"] = (
                None if release is None else float(_release_cost(release["released_years"], premium))
            )
        grid.append(entry)
    return grid


def build_release_cost_book(
    *,
    policies: Any,
    customers: Any = None,
    applications: Any = None,
    tables: Optional[Mapping[str, Any]] = None,
    tables_version: str = "",
    discount_rate: float = 0.0,
    premium_payment_years: Optional[int] = None,
    projection_years: int = PROJECTION_YEARS_DEFAULT,
    as_of: Optional[date] = None,
    exclude_customer: Optional[Callable[[str], bool]] = None,
    only_customer_id: Optional[str] = None,
    case: Optional[Mapping[str, Any]] = None,
    reference_annual_premium: Any = None,
    include_projections: bool = False,
) -> Dict[str, Any]:
    """The release-cost test over the registered policies. Writes nothing."""
    today = as_of or datetime.now(timezone.utc).date()
    basis = _Basis(tables or {}, tables_version, discount_rate, premium_payment_years,
                   projection_years, today)
    application_index = _index_applications(applications)
    wanted = None if only_customer_id is None else str(only_customer_id)

    assessed: List[Dict[str, Any]] = []
    withheld: List[Dict[str, Any]] = []
    out_of_scope: Dict[str, int] = {}
    registered = suspended = in_force = 0
    seen: set = set()
    duplicates: List[str] = []
    customer_cache: Dict[str, Optional[Mapping[str, Any]]] = {}

    def customer_of(customer_id: str) -> Optional[Mapping[str, Any]]:
        if customer_id not in customer_cache:
            found = None
            if customer_id and customers is not None:
                try:
                    found = customers.get(customer_id)
                except Exception:
                    found = None
            customer_cache[customer_id] = found if isinstance(found, Mapping) else None
        return customer_cache[customer_id]

    for key, policy in _policy_items(policies):
        pid = _policy_id(policy, key)
        customer_id = str(policy.get("customer_id") or "")
        if wanted is not None and customer_id != wanted:
            continue
        if exclude_customer is not None and customer_id and exclude_customer(customer_id):
            suspended += 1
            continue
        registered += 1
        status = _status(policy)
        if status not in IN_FORCE_STATUSES:
            label = status or "no_status"
            out_of_scope[label] = out_of_scope.get(label, 0) + 1
            continue
        in_force += 1
        if pid in seen:
            duplicates.append(pid)
            continue
        seen.add(pid)
        application = (
            application_index.get(str(policy.get("underwriting_id") or ""))
            or application_index.get("policy:" + pid)
        )
        customer = customer_of(customer_id)
        row = assess_policy(basis, policy, application=application, customer=customer, policy_id=pid)
        row["customer_name"] = _customer_name(customer)
        if row["status"] == "assessed":
            assessed.append(row)
        else:
            withheld.append({
                key_: row.get(key_) for key_ in (
                    "policy_id", "customer_id", "customer_name", "policy_type", "annual_premium",
                    "attained_age", "age_source", "sex_used", "reason",
                )
            })

    # Per-year projection of the whole book.
    by_year: Dict[int, Dict[str, Any]] = {}
    for row in assessed:
        for year in row["projection"]:
            slot = by_year.setdefault(year["year"], {
                "year": year["year"], "calendar_year": year["calendar_year"],
                "policies_exposed": 0, "_cost": _ZERO, "_expected": _ZERO, "_pv": _ZERO,
            })
            slot["policies_exposed"] += 1
            slot["_cost"] += Decimal(str(year["release_cost"]))
            slot["_expected"] += Decimal(str(year["expected_release_cost"]))
            slot["_pv"] += Decimal(str(year["discounted_expected_release_cost"]))
    projection = []
    cumulative = _ZERO
    for year in sorted(by_year):
        slot = by_year[year]
        cumulative += slot["_pv"]
        projection.append({
            "year": slot["year"],
            "calendar_year": slot["calendar_year"],
            "policies_exposed": slot["policies_exposed"],
            "release_cost_at_risk": float(_cents(slot["_cost"])),
            "expected_release_cost": float(_cents(slot["_expected"])),
            "discounted_expected_release_cost": float(_cents(slot["_pv"])),
            "cumulative_discounted": float(_cents(cumulative)),
        })

    premium_total = _sum(assessed, "annual_premium")
    cost_total = _sum(assessed, "release_cost")
    expected_year1 = _sum(assessed, "expected_release_cost_year1")
    expected_projected = _sum(assessed, "expected_release_cost_projected")
    pv_total = _sum(assessed, "expected_release_cost_pv")

    with_sum = [row for row in assessed if row.get("disability_sum") is not None]
    sum_total = _sum(with_sum, "disability_sum")
    sum_cost = _sum(with_sum, "release_cost")
    with_expected = [row for row in with_sum if row.get("expected_disability_claim_year1") is not None]
    expected_claims = _sum(with_expected, "expected_disability_claim_year1")
    adjusted_expected = _sum(with_expected, "adjusted_expected_disability_year1")
    sum_basis_counts: Dict[str, int] = {}
    priced_basis_counts: Dict[str, int] = {}
    for row in assessed:
        label = str(row.get("disability_sum_basis") or "")
        sum_basis_counts[label] = sum_basis_counts.get(label, 0) + 1
        label = str(row.get("priced_risk_basis") or "")
        priced_basis_counts[label] = priced_basis_counts.get(label, 0) + 1
    priced = [row for row in assessed
              if row.get("adjusted_disability_premium_annual") is not None]
    priced_disability = _sum(priced, "disability_premium_annual")
    priced_expected = _sum(priced, "expected_release_cost_year1")
    priced_adjusted = _sum(priced, "adjusted_disability_premium_annual")
    priced_risk_rows = [row for row in assessed if row.get("adjusted_risk_premium_annual") is not None]
    priced_risk = _sum(priced_risk_rows, "risk_premium_annual")
    priced_risk_expected = _sum(priced_risk_rows, "expected_release_cost_year1")
    priced_risk_adjusted = _sum(priced_risk_rows, "adjusted_risk_premium_annual")

    # Customers.
    grouped: Dict[str, Dict[str, Any]] = {}
    for row in assessed:
        slot = grouped.setdefault(row["customer_id"], {
            "customer_id": row["customer_id"], "customer_name": row.get("customer_name") or "",
            "policies": 0, "policy_ids": [], "withheld_policies": 0, "_rows": [],
        })
        slot["policies"] += 1
        slot["policy_ids"].append(row["policy_id"])
        slot["_rows"].append(row)
    for item in withheld:
        slot = grouped.setdefault(str(item.get("customer_id") or ""), {
            "customer_id": str(item.get("customer_id") or ""),
            "customer_name": item.get("customer_name") or "",
            "policies": 0, "policy_ids": [], "withheld_policies": 0, "_rows": [],
        })
        slot["withheld_policies"] += 1
    customer_rows = []
    for slot in grouped.values():
        rows = slot.pop("_rows")
        slot["annual_premium"] = float(_sum(rows, "annual_premium"))
        slot["release_cost"] = float(_sum(rows, "release_cost"))
        slot["expected_release_cost_year1"] = float(_sum(rows, "expected_release_cost_year1"))
        slot["expected_release_cost_pv"] = float(_sum(rows, "expected_release_cost_pv"))
        slot["integrity_hash"] = _sha({
            "customer_id": slot["customer_id"],
            "rows": sorted(row["integrity_hash"] for row in rows),
            "release_cost": slot["release_cost"],
        })
        customer_rows.append(slot)
    customer_rows.sort(key=lambda item: (-item["release_cost"], item["customer_id"]))

    # Age band and sex.
    bands: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for row in assessed:
        band_key = (_age_band(row["attained_age"]), row["sex_used"])
        slot = bands.setdefault(band_key, {
            "age_band": band_key[0], "sex_used": band_key[1], "policies": 0, "_rows": [],
            "_weighted_years": _ZERO,
        })
        slot["policies"] += 1
        slot["_rows"].append(row)
        slot["_weighted_years"] += Decimal(str(row["released_years"])) * Decimal(str(row["annual_premium"]))
    band_rows = []
    for band_key in sorted(bands):
        slot = bands[band_key]
        rows = slot.pop("_rows")
        weighted = slot.pop("_weighted_years")
        premium = _sum(rows, "annual_premium")
        slot["annual_premium"] = float(premium)
        slot["release_cost"] = float(_sum(rows, "release_cost"))
        slot["premium_weighted_released_years"] = (
            None if premium <= 0 else round(float(weighted / premium), 6)
        )
        band_rows.append(slot)

    withheld_reasons: Dict[str, int] = {}
    for item in withheld:
        reason = str(item.get("reason") or "")
        withheld_reasons[reason] = withheld_reasons.get(reason, 0) + 1
    age_sources: Dict[str, int] = {}
    sex_basis: Dict[str, int] = {}
    for row in assessed:
        age_sources[row["age_source"]] = age_sources.get(row["age_source"], 0) + 1
        sex_basis[row["sex_basis"]] = sex_basis.get(row["sex_basis"], 0) + 1

    registered_customers = None
    if customers is not None and wanted is None:
        try:
            registered_customers = sum(
                1 for customer_id in list(customers.keys())
                if not (exclude_customer is not None and exclude_customer(str(customer_id)))
            )
        except Exception:
            registered_customers = None

    totals = {
        "annual_premium": float(premium_total),
        "release_cost": float(cost_total),
        "release_cost_to_premium": (
            None if premium_total <= 0 else round(float(cost_total / premium_total), 6)
        ),
        "expected_release_cost_year1": float(expected_year1),
        "hedge_pct_of_annual_premium": (
            None if premium_total <= 0 else round(float(expected_year1 / premium_total * 100), 4)
        ),
        "expected_release_cost_projected": float(expected_projected),
        "expected_release_cost_pv": float(pv_total),
    }
    adjusted_risk = {
        "basis": (
            "Premium view: the disability and risk premium the kernel pinned at issue, plus "
            "the expected release cost of the next 12 months. Exposure view: the disability "
            "sum pinned at issue, plus the release cost. A policy with no pin is counted and "
            "not estimated."
        ),
        "policies_with_priced_disability_premium": len(priced),
        "policies_without_priced_disability_premium": len(assessed) - len(priced),
        "priced_risk_basis": priced_basis_counts,
        "disability_premium_annual": float(priced_disability),
        "expected_release_cost_on_those_policies": float(priced_expected),
        "adjusted_disability_premium_annual": float(priced_adjusted),
        "disability_premium_uplift_pct": (
            None if priced_disability <= 0
            else round(float(priced_expected / priced_disability * 100), 4)
        ),
        "risk_premium_annual": float(priced_risk),
        "adjusted_risk_premium_annual": float(priced_risk_adjusted),
        "risk_premium_uplift_pct": (
            None if priced_risk <= 0 else round(float(priced_risk_expected / priced_risk * 100), 4)
        ),
        "policies_with_disability_sum": len(with_sum),
        "policies_without_disability_sum": len(assessed) - len(with_sum),
        "disability_sum_basis": sum_basis_counts,
        "disability_sum": float(sum_total),
        "release_cost_on_those_policies": float(sum_cost),
        "adjusted_disability_exposure": float(sum_total + sum_cost),
        "risk_uplift_pct": None if sum_total <= 0 else round(float(sum_cost / sum_total * 100), 4),
        "expected_disability_claims_year1": float(expected_claims),
        "adjusted_expected_disability_year1": float(adjusted_expected),
        "expected_uplift_pct": (
            None if expected_claims <= 0
            else round(float((adjusted_expected - expected_claims) / expected_claims * 100), 4)
        ),
    }
    summary = {
        "customers_registered": registered_customers,
        "customers_with_assessed_policy": len({row["customer_id"] for row in assessed}),
        "policies_registered": registered,
        "policies_in_force": in_force,
        "policies_assessed": len(assessed),
        "policies_withheld": len(withheld),
        "withheld_reasons": withheld_reasons,
        "policies_not_in_force_by_status": dict(sorted(out_of_scope.items())),
        "policies_on_suspended_accounts": suspended,
        "age_sources": age_sources,
        "sex_basis": sex_basis,
    }

    checks = _integrity_checks(
        basis, assessed, withheld, duplicates, in_force, totals, customer_rows, projection,
        adjusted_risk,
    )
    reference_premium = _money(reference_annual_premium)
    if reference_premium is None or reference_premium <= 0:
        reference_premium = (
            _cents(premium_total / len(assessed)) if assessed else DEFAULT_REFERENCE_PREMIUM
        )

    case_result = None
    if case is not None:
        case_result = release_case(
            basis, age=int(case["age"]), sex_used=str(case["sex"]),
            annual_premium=Decimal(str(case["annual_premium"])),
            years_paid=int(case.get("years_paid") or 0),
        )

    listed = []
    for row in assessed[:MAX_LISTED_ROWS]:
        entry = dict(row)
        if not include_projections:
            entry.pop("projection", None)
        listed.append(entry)

    result_hash = _sha({
        "test": TEST_ID,
        "method": METHOD_VERSION,
        "table": basis.table_hash,
        "parameters": basis.parameters(),
        "scope": wanted,
        "rows": [row["integrity_hash"] for row in assessed],
        "withheld": [[item.get("policy_id"), item.get("reason")] for item in withheld],
        "totals": totals,
        "adjusted_risk": adjusted_risk,
    })

    return {
        "test": TEST_ID,
        "method_version": METHOD_VERSION,
        "basis": BASIS_NOTE,
        "projection_basis": PROJECTION_NOTE,
        "writes_nothing": True,
        "parameters": basis.parameters(),
        "table": {
            "table_type": TABLE_NAME,
            "label": "ADL 3 disabled life expectancy — Global (assumption)",
            "tables_version": basis.tables_version,
            "row_count": len(basis.rows),
            "integrity_hash": basis.table_hash,
            "used_in_pricing": False,
        },
        "summary": summary,
        "totals": totals,
        "adjusted_risk": adjusted_risk,
        "projection": projection,
        "by_age_band": band_rows,
        "customers": customer_rows[:MAX_LISTED_ROWS],
        "customers_total": len(customer_rows),
        "policies": listed,
        "policies_listed": len(listed),
        "policies_total": len(assessed),
        "withheld": withheld[:MAX_LISTED_ROWS],
        "withheld_total": len(withheld),
        "reference": {
            "annual_premium": float(reference_premium),
            "years_paid": 0,
            "rows": _reference_grid(basis, reference_premium),
        },
        "case": case_result,
        "integrity": {
            "ok": all(check["ok"] for check in checks),
            "checks": checks,
            "result_hash": result_hash,
        },
    }


def _integrity_checks(basis: _Basis, assessed: List[Dict[str, Any]], withheld: List[Dict[str, Any]],
                      duplicates: List[str], in_force: int, totals: Mapping[str, Any],
                      customer_rows: List[Dict[str, Any]],
                      projection: List[Dict[str, Any]],
                      adjusted_risk: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Identities the result must hold. Each is recomputed from the table."""
    checks: List[Dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    broken_rows = [
        row.get("age") for row in basis.rows
        if isinstance(row, dict) and adl3_row_at([row], _int_or_none(row.get("age")) or -1) is None
    ]
    add("expectancy_table_rows_complete", bool(basis.rows) and not broken_rows,
        f"{len(basis.rows)} rows, {len(broken_rows)} without male, female and average years")

    mismatched = []
    for row in assessed:
        years = basis.expectancy(row["attained_age"], row["sex_used"])
        if years is None:
            mismatched.append(row["policy_id"])
            continue
        if basis.premium_payment_years is not None:
            years = min(years, float(max(0, basis.premium_payment_years - row["years_paid"])))
        expected = _release_cost(years, Decimal(str(row["annual_premium"])))
        if expected != Decimal(str(row["release_cost"])) or _row_hash(basis, row) != row["integrity_hash"]:
            mismatched.append(row["policy_id"])
    add("release_cost_is_years_times_premium", not mismatched,
        f"{len(assessed)} policies recomputed from the table, {len(mismatched)} differ")

    row_total = _sum(assessed, "release_cost")
    add("totals_tie_to_policies", row_total == Decimal(str(totals["release_cost"]))
        and _sum(assessed, "annual_premium") == Decimal(str(totals["annual_premium"])),
        f"policies sum to {row_total}, total {totals['release_cost']}")

    customer_total = _sum(customer_rows, "release_cost")
    add("customer_books_tie_to_total", customer_total == row_total,
        f"customer books sum to {customer_total}, total {row_total}")

    add("every_in_force_policy_counted_once",
        not duplicates and len(assessed) + len(withheld) == in_force,
        f"{in_force} in force = {len(assessed)} assessed + {len(withheld)} withheld, "
        f"{len(duplicates)} repeated ids")

    first_year = Decimal(str(projection[0]["release_cost_at_risk"])) if projection else _ZERO
    projected_first = _sum(
        [row for row in assessed if row.get("projection")], "release_cost",
    )
    add("projection_year_one_ties_to_release_cost", first_year == projected_first,
        f"projection year 1 at risk {first_year}, policies projected {projected_first}")

    expected_rows = _sum(assessed, "expected_release_cost_projected")
    expected_years = _cents(sum(
        (Decimal(str(year["expected_release_cost"])) for year in projection), _ZERO,
    ))
    add("projection_ties_to_policies", expected_rows == expected_years,
        f"policies sum to {expected_rows}, projection years sum to {expected_years}")

    priced = Decimal(str(adjusted_risk["disability_premium_annual"]))
    added = Decimal(str(adjusted_risk["expected_release_cost_on_those_policies"]))
    adjusted = Decimal(str(adjusted_risk["adjusted_disability_premium_annual"]))
    exposure = Decimal(str(adjusted_risk["adjusted_disability_exposure"]))
    exposure_parts = (Decimal(str(adjusted_risk["disability_sum"]))
                      + Decimal(str(adjusted_risk["release_cost_on_those_policies"])))
    add("adjusted_risk_is_priced_risk_plus_release_cost",
        adjusted == priced + added and exposure == exposure_parts,
        f"priced {priced} + expected release {added} = {priced + added}, adjusted {adjusted}")
    return checks


# ---------------------------------------------------------------------------
# One customer's book
# ---------------------------------------------------------------------------

_CUSTOMER_ROW_KEYS = (
    "policy_id", "policy_type", "policy_status", "annual_premium", "attained_age", "age_source",
    "sex_used", "sex_basis", "years_paid", "premium_payment_years", "remaining_payment_years",
    "expectancy_years", "released_years", "release_cost", "integrity_hash",
)


def customer_release_cost(book: Mapping[str, Any], customer_id: str) -> Dict[str, Any]:
    """The customer's own rows of a book built with ``only_customer_id``.

    Carries the release cost only. The incidence, the expected cost and the
    exposure figures stay on the actuarial view.
    """
    wanted = str(customer_id or "")
    rows = [
        {key: row.get(key) for key in _CUSTOMER_ROW_KEYS}
        for row in book.get("policies") or []
        if str(row.get("customer_id") or "") == wanted
    ]
    withheld = [
        {key: item.get(key) for key in ("policy_id", "policy_type", "annual_premium", "reason")}
        for item in book.get("withheld") or []
        if str(item.get("customer_id") or "") == wanted
    ]
    premium = _sum(rows, "annual_premium")
    cost = _sum(rows, "release_cost")
    integrity = book.get("integrity") or {}
    return {
        "test": TEST_ID,
        "basis": BASIS_NOTE,
        "writes_nothing": True,
        "customer_id": wanted,
        "parameters": dict(book.get("parameters") or {}),
        "table": dict(book.get("table") or {}),
        "policies": rows,
        "withheld": withheld,
        "totals": {
            "policies": len(rows),
            "annual_premium": float(premium),
            "release_cost": float(cost),
        },
        "integrity": {
            "ok": bool(integrity.get("ok")) and cost == _sum(
                [row for row in book.get("policies") or []
                 if str(row.get("customer_id") or "") == wanted], "release_cost"),
            "result_hash": _sha({
                "customer_id": wanted,
                "book": integrity.get("result_hash"),
                "rows": [row.get("integrity_hash") for row in rows],
                "release_cost": float(cost),
            }),
        },
    }
