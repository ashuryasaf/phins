"""Admin AI & BI desk.

Read-only answers for an admin or a manager. Every figure is computed from
data that already exists: the actuarial tables, the published ADL 3
remaining-life rows, ``SimulationParams`` (the standard age distribution),
the in-memory or database books, and simulations already stored on the
process. A missing rate stays missing. This module does not write those
stores, does not draw a new random portfolio, and does not let a language
model introduce a number.

A question that needs a new draw, a changed assumption, or a plan that is
not in the stored formulas is returned with ``planning`` pointing at the
existing tool that can run it. The desk does not estimate that result.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import secrets
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from security.access_hierarchy import (
    CUSTOMER_PRIVATE_PAGES,
    PRIVATE_PORTAL_PAGES,
    SHARED_OPERATIONAL_PAGES,
    STAFF_PAGES,
    page_roles,
)
from services.actuarial_service import (
    SimulationParams,
    _mortality_terminal_age,
    _normal_bin_count,
    curtate_life_expectancy,
    get_actuarial_store,
    portfolio_adl_weights,
)
from services.adl3_disabled_life_expectancy import adl3_row_at, adl3_rows_for_tables

FORMULA_ID = "admin_ai_bi_v1"
ALLOWED_ROLES = frozenset({"admin", "manager"})
_MAX_REPORTS = 48
_LOCK = threading.Lock()
_REPORTS: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()

_HEBREW = re.compile(r"[\u0590-\u05FF]")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_CUST_ID = re.compile(r"\b(CUST-[A-Za-z0-9_-]+)\b", re.I)
_SIM_ID = re.compile(r"\b(SIM-[A-Za-z0-9_-]+)\b", re.I)
_EMAIL = re.compile(r"\b([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})\b", re.I)

_KEEP_KEYS = frozenset({"national_id_hash", "national_id_last4", "nationality"})
_REDACT_KEYS = frozenset({
    "password", "password_hash", "passwd", "secret", "token", "api_key",
    "national_id", "id_number", "ssn", "card_number", "cvv", "pan",
    "account_number", "routing_number", "otp", "authorization",
})

_STATIC = Path(__file__).resolve().parents[1] / "web_portal" / "static"

_LABELS: Dict[str, Tuple[str, str]] = {
    "/admin.html": ("Admin overview", "סקירת מנהל"),
    "/admin-portal.html": ("Admin portal", "פורטל מנהל"),
    "/admin-desk.html": ("Admin desk", "שולחן מנהל"),
    "/admin-agents.html": ("Agents", "סוכנים"),
    "/admin-foundations.html": ("Community", "קהילה"),
    "/admin-supplier-dashboard.html": ("Suppliers", "ספקים"),
    "/admin-media.html": ("Media", "מדיה"),
    "/admin-ai-report.html": ("AI & BI report", "דוח AI ו-BI"),
    "/underwriter-dashboard.html": ("Underwriting", "חיתום"),
    "/claims-adjuster-dashboard.html": ("Claims", "תביעות"),
    "/accountant-dashboard.html": ("Accountant", "הנהלת חשבונות"),
    "/actuary-dashboard.html": ("Actuary", "אקטואריה"),
    "/customer-management.html": ("Customer book", "ספר לקוחות"),
    "/unified-workbench.html": ("Workbench", "עמדת עבודה"),
    "/risk-dashboard.html": ("Risk", "סיכון"),
    "/risk-reports-dashboard.html": ("Risk reports", "דוחות סיכון"),
    "/video-agents.html": ("Video agents", "סוכני וידאו"),
    "/pitch-dashboard.html": ("IL pitch", "מצגת"),
    "/corporate-legal-dashboard.html": ("Legal", "משפטי"),
    "/nda-dashboard.html": ("NDA", "הסכם סודיות"),
    "/settlement-approval.html": ("Settlements", "סליקה"),
    "/assessment-center.html": ("Assessments", "הערכות"),
    "/billing.html": ("Billing", "חיוב"),
    "/documents.html": ("Documents", "מסמכים"),
    "/cyber-security.html": ("Cyber security", "סייבר"),
    "/chat-process-review.html": ("Chat review", "סקירת שיחה"),
    "/customer-ai-report.html": ("Customer AI report", "דוח AI ללקוח"),
    "/risk-assessment-viewer.html": ("Risk assessment", "הערכת סיכון"),
    "/storyboard-editor.html": ("Storyboard", "לוח סיפור"),
    "/foundation-dashboard.html": ("Foundation", "קרן"),
    "/regulator-dashboard.html": ("Regulator", "רגולטור"),
    "/supplier-dashboard.html": ("Supplier desk", "שולחן ספק"),
    "/agent-portal.html": ("Agent portal", "פורטל סוכן"),
    "/dashboard.html": ("Customer home", "בית לקוח"),
    "/savings-portfolio.html": ("Investments", "השקעות"),
    "/algo-trading.html": ("Trading", "מסחר"),
    "/mislaka-report.html": ("Mislaka", "מסלקה"),
    "/file-a-claim.html": ("File a claim", "הגשת תביעה"),
    "/claims-chat.html": ("Claims chat", "שיחת תביעה"),
    "/apply.html": ("Application form", "טופס הצטרפות"),
    "/apply-chat.html": ("Application chat", "שיחת הצטרפות"),
}


class AdminAIBiError(ValueError):
    """A question or a variant the desk will not compute."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _norm_num(token: str) -> str:
    text = str(token).replace(",", "")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def numbers_in(value: Any) -> set:
    """Numeric tokens in a JSON value or a sentence, trailing zeros ignored."""
    if isinstance(value, str):
        return {_norm_num(token) for token in _NUMBER.findall(value)}
    return {_norm_num(token) for token in _NUMBER.findall(_canonical(value))}


def authorize(role: Optional[str]) -> bool:
    return str(role or "").strip().lower() in ALLOWED_ROLES


def _title_from_path(path: str) -> str:
    name = path.rsplit("/", 1)[-1].replace(".html", "").replace("-", " ").strip()
    return name[:1].upper() + name[1:] if name else path


def _dashboard_paths() -> List[str]:
    paths = set(STAFF_PAGES) | set(SHARED_OPERATIONAL_PAGES) | set(CUSTOMER_PRIVATE_PAGES)
    paths.add("/admin-ai-report.html")
    paths.add("/cyber-security.html")
    if _STATIC.is_dir():
        for file in _STATIC.glob("*.html"):
            name = file.name
            if "dashboard" in name or name in {
                "admin.html", "admin-portal.html", "admin-desk.html", "admin-media.html",
                "admin-agents.html", "admin-foundations.html", "billing.html",
                "documents.html", "assessment-center.html", "cyber-security.html",
                "video-agents.html", "storyboard-editor.html", "chat-process-review.html",
                "customer-management.html", "customer-ai-report.html",
                "risk-assessment-viewer.html", "settlement-approval.html",
                "admin-ai-report.html",
            }:
                paths.add("/" + name)
    return sorted(paths)


def _page_access(path: str) -> Tuple[bool, List[str]]:
    if path in CUSTOMER_PRIVATE_PAGES:
        return False, ["customer"]
    if path in PRIVATE_PORTAL_PAGES:
        return False, sorted(PRIVATE_PORTAL_PAGES[path])
    if path in STAFF_PAGES:
        roles = page_roles(path)
        return "admin" in roles, sorted(roles)
    if path in SHARED_OPERATIONAL_PAGES:
        return True, ["admin", "customer"]
    return True, ["admin"]


def dashboard_catalog() -> List[Dict[str, Any]]:
    """Every dashboard the desk can name. New staff pages appear on their own."""
    rows = []
    for path in _dashboard_paths():
        admin_open, roles = _page_access(path)
        label_en, label_he = _LABELS.get(path, (_title_from_path(path), _title_from_path(path)))
        group = "staff"
        if path in CUSTOMER_PRIVATE_PAGES:
            group = "customer"
        elif path in SHARED_OPERATIONAL_PAGES:
            group = "shared"
        elif path in PRIVATE_PORTAL_PAGES:
            group = "other_role"
        rows.append({
            "path": path,
            "label_en": label_en,
            "label_he": label_he,
            "group": group,
            "admin_open": bool(admin_open),
            "roles": roles,
        })
    rows.sort(key=lambda row: (not row["admin_open"], row["label_en"].lower()))
    return rows


def _rate_per_life(tables: Mapping[str, Any], table_key: str, age: int) -> Optional[float]:
    """Same bracket rule as ``ActuarialTablesStore.lookup_table_rate``.

    An age with no bracket is None. It is not filled with zero.
    """
    for bracket in (tables or {}).get(table_key) or []:
        if not isinstance(bracket, dict):
            continue
        try:
            lo = int(bracket.get("age_min", 0))
            hi = int(bracket.get("age_max", 0))
            rate = float(bracket.get("rate_per_1000", 0.0)) / 1000.0
        except (TypeError, ValueError):
            continue
        if lo <= int(age) < hi:
            return rate
    return None


def _standard() -> Dict[str, Any]:
    params = SimulationParams()
    return {
        "population": int(params.customer_count),
        "age_min": int(params.age_min),
        "age_max": int(params.age_max),
        "mean": float(params.age_mean),
        "std": float(params.age_std),
        "distribution": str(params.age_distribution),
        "source": "services.actuarial_service.SimulationParams",
    }


def _parse_population(question: str) -> Optional[int]:
    match = re.search(r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*k\b", question, re.I)
    if match:
        return int(round(float(match.group(1).replace(",", "")) * 1000))
    match = re.search(r"(\d{1,3}(?:,\d{3})+)", question)
    if match:
        return int(match.group(1).replace(",", ""))
    # A bare 4-digit calendar year, including the year in 2026-10-23,
    # is not a cohort size. The standard book stays in place.
    for match in re.finditer(r"\b(\d{4,8})\b", question):
        token = match.group(1)
        number = int(token)
        if len(token) == 4 and 1900 <= number <= 2100:
            continue
        return number
    return None


def _parse_age_floor(question: str) -> Optional[int]:
    match = re.search(r"(\d{1,3})\s*\+", question)
    if match:
        return int(match.group(1))
    match = re.search(r"(?:age|aged|גיל)\s*(\d{1,3})", question, re.I)
    if match:
        return int(match.group(1))
    return None


def _as_int(value: Any, name: str, lo: int, hi: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise AdminAIBiError(f"{name} must be an integer")
    if number < lo or number > hi:
        raise AdminAIBiError(f"{name} must be between {lo} and {hi}")
    return number


def _as_float(value: Any, name: str, lo: float, hi: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise AdminAIBiError(f"{name} must be a number")
    if number < lo or number > hi:
        raise AdminAIBiError(f"{name} must be between {lo} and {hi}")
    return number


def resolve_variants(question: str, overrides: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Standard parameters, then numbers written in the question, then the form."""
    standard = _standard()
    applied = {
        "population": standard["population"],
        "age_floor": 85,
        "age_cap": 120,
        "age_min": standard["age_min"],
        "age_max": standard["age_max"],
        "mean": standard["mean"],
        "std": standard["std"],
        "distribution": "both",
        "sex": "average",
        "adl_basis": "incidence",
    }
    population = _parse_population(question or "")
    if population is not None:
        applied["population"] = population
    floor = _parse_age_floor(question or "")
    if floor is not None:
        applied["age_floor"] = floor
    for key, value in dict(overrides or {}).items():
        if value is None or value == "":
            continue
        if key in applied:
            applied[key] = value
    applied["population"] = _as_int(applied["population"], "population", 1, 10_000_000)
    applied["age_floor"] = _as_int(applied["age_floor"], "age_floor", 0, 120)
    applied["age_cap"] = _as_int(applied["age_cap"], "age_cap", 0, 120)
    applied["age_min"] = _as_int(applied["age_min"], "age_min", 0, 120)
    applied["age_max"] = _as_int(applied["age_max"], "age_max", 0, 120)
    applied["mean"] = _as_float(applied["mean"], "mean", 0.0, 120.0)
    applied["std"] = _as_float(applied["std"], "std", 0.01, 40.0)
    if applied["age_floor"] > applied["age_cap"]:
        raise AdminAIBiError("age_floor cannot be above age_cap")
    if applied["age_min"] > applied["age_max"]:
        raise AdminAIBiError("age_min cannot be above age_max")
    if applied["distribution"] not in ("both", "open_normal", "portfolio_window"):
        raise AdminAIBiError("distribution is not a known variant")
    if applied["sex"] not in ("average", "male", "female"):
        raise AdminAIBiError("sex is not a known variant")
    if applied["adl_basis"] not in ("incidence", "portfolio_adl_3", "decline_threshold"):
        raise AdminAIBiError("adl_basis is not a known variant")
    # A population typed in the question keeps the standard shape at a
    # chosen size. Mean, spread, and the draw window are the scenario knobs.
    applied["scenario"] = bool(
        applied["mean"] != standard["mean"]
        or applied["std"] != standard["std"]
        or applied["age_min"] != standard["age_min"]
        or applied["age_max"] != standard["age_max"]
    )
    return applied


def _share_at_or_above(weights: Sequence[float], level: int) -> Optional[float]:
    total = float(sum(weights))
    if total <= 0.0:
        return None
    start = max(0, int(level) - 1)
    return float(sum(weights[start:])) / total


def _bin_counts(population: int, mean: float, std: float, lo: int, hi: int) -> List[Tuple[int, float]]:
    return [
        (age, float(_normal_bin_count(age, mean, std, population)))
        for age in range(int(lo), int(hi) + 1)
    ]


def _window_counts(applied: Mapping[str, Any], lo: int, hi: int) -> Tuple[List[Tuple[int, float]], bool]:
    """Truncated normal used by the portfolio simulator, restricted to [lo, hi]."""
    window = _bin_counts(1, applied["mean"], applied["std"], applied["age_min"], applied["age_max"])
    mass = sum(weight for _age, weight in window)
    identity = mass > 0.0
    rows = []
    if not identity:
        return rows, False
    scale = float(applied["population"]) / mass
    for age, weight in window:
        if lo <= age <= hi:
            rows.append((age, weight * scale))
    full = [(age, weight * scale) for age, weight in window]
    summed = sum(weight for _age, weight in full)
    return rows, abs(summed - float(applied["population"])) <= 1e-4


def _weighted(rows: Sequence[Tuple[int, float, Optional[float]]]) -> Tuple[Optional[float], List[int], float]:
    """Count-weighted mean. Ages with a missing value are withheld, not zero."""
    num = 0.0
    den = 0.0
    missing: List[int] = []
    missed_mass = 0.0
    for age, count, value in rows:
        if count <= 1e-8:
            continue
        if value is None:
            missing.append(age)
            missed_mass += count
            continue
        num += count * float(value)
        den += count
    if den <= 0.0:
        return None, missing, missed_mass
    return round(num / den, 4), missing, missed_mass


def _load_tables(tables: Optional[Mapping[str, Any]], config: Any) -> Tuple[Dict[str, Any], Any, str]:
    version = "supplied"
    if tables is None or config is None:
        store = get_actuarial_store()
        if tables is None:
            tables = store.get_current_tables()
        if config is None:
            config = store.config
        version = str(getattr(store, "current_version", None) or "active")
    return dict(tables or {}), config, version


def build_cohort(applied: Mapping[str, Any], tables: Mapping[str, Any], config: Any,
                 tables_version: str) -> Dict[str, Any]:
    """Expected lives, ADL incidence, and remaining years for one age floor."""
    floor = int(applied["age_floor"])
    cap = int(applied["age_cap"])
    open_rows = _bin_counts(applied["population"], applied["mean"], applied["std"], floor, cap)
    open_lives = float(sum(count for _age, count in open_rows))
    full_open = _bin_counts(applied["population"], applied["mean"], applied["std"], 0, 120)
    open_mass = float(sum(count for _age, count in full_open))
    window_rows, window_identity = _window_counts(applied, floor, cap)
    window_lives = float(sum(count for _age, count in window_rows))

    threshold = 9
    try:
        threshold = int(getattr(config, "decline_threshold", 9))
    except (TypeError, ValueError):
        threshold = 9
    research = adl3_rows_for_tables(dict(tables))
    terminal = _mortality_terminal_age(list(tables.get("mortality_rates") or []))

    def qx_at(age: int) -> Optional[float]:
        return _rate_per_life(tables, "mortality_rates", age)

    detailed = []
    incidence_num = 0.0
    incidence_den = 0.0
    incidence_missing: List[int] = []
    incidence_missing_mass = 0.0
    mix3_num = 0.0
    mix3_den = 0.0
    mix3_missing: List[int] = []
    mix3_missing_mass = 0.0
    decline_num = 0.0
    decline_den = 0.0
    decline_missing: List[int] = []
    decline_missing_mass = 0.0
    year_rows = {"average_years": [], "male_years": [], "female_years": [], "healthy_curtate_years": []}

    for age, count in open_rows:
        incidence = _rate_per_life(tables, "disability_incidence_rates", age)
        research_row = adl3_row_at(research, age)
        healthy = curtate_life_expectancy(age, qx_at, terminal, 1.0)
        weights = portfolio_adl_weights(age, dict(tables))
        share3 = _share_at_or_above(weights, 3)
        share_decline = _share_at_or_above(weights, threshold)
        if count > 1e-8:
            if incidence is None:
                incidence_missing.append(age)
                incidence_missing_mass += count
            else:
                incidence_num += count * incidence
                incidence_den += count
            if share3 is None:
                mix3_missing.append(age)
                mix3_missing_mass += count
            else:
                mix3_num += count * share3
                mix3_den += count
            if share_decline is None:
                decline_missing.append(age)
                decline_missing_mass += count
            else:
                decline_num += count * share_decline
                decline_den += count
        average = None if research_row is None else research_row.get("average_years")
        male = None if research_row is None else research_row.get("male_years")
        female = None if research_row is None else research_row.get("female_years")
        year_rows["average_years"].append((age, count, average))
        year_rows["male_years"].append((age, count, male))
        year_rows["female_years"].append((age, count, female))
        year_rows["healthy_curtate_years"].append((age, count, healthy))
        if count >= 1e-6 or age == floor:
            detailed.append({
                "age": age,
                "lives": round(count, 6),
                "disability_incidence_per_life": None if incidence is None else round(incidence, 6),
                "portfolio_adl_3_share": None if share3 is None else round(share3, 6),
                "decline_share": None if share_decline is None else round(share_decline, 6),
                "adl3_average_years": average,
                "adl3_male_years": male,
                "adl3_female_years": female,
                "healthy_curtate_years": healthy,
            })

    def _mean(key: str) -> Tuple[Optional[float], List[int]]:
        value, missing, _mass = _weighted(year_rows[key])
        return value, missing

    avg, avg_missing = _mean("average_years")
    male_w, male_missing = _mean("male_years")
    female_w, female_missing = _mean("female_years")
    healthy_w, healthy_missing = _mean("healthy_curtate_years")
    floor_row = adl3_row_at(research, floor)
    floor_healthy = curtate_life_expectancy(floor, qx_at, terminal, 1.0)
    basis = "cohort_weighted" if open_lives > 0.0 and avg is not None else "age_floor_person"

    decades = []
    for lo in range(0, 121, 10):
        hi = min(lo + 9, 120)
        lives = float(sum(count for age, count in full_open if lo <= age <= hi))
        decades.append({"age_min": lo, "age_max": hi, "lives": round(lives, 4)})
    decade_sum = float(sum(row["lives"] for row in decades))

    def _portion(num: float, den: float, missing: List[int]) -> Optional[float]:
        # Covered ages still answer. Uncovered ages stay in the withheld list
        # and are not filled with zero or with a neighbouring rate.
        del missing
        if den <= 0.0:
            return None
        return round(num, 6)

    outside = floor > int(applied["age_max"]) or cap < int(applied["age_min"])
    return {
        "standard": _standard(),
        "applied": dict(applied),
        "tables_version": tables_version,
        "decline_threshold": threshold,
        "portfolio_window": {
            "lives": round(window_lives, 6),
            "outside_draw_window": bool(outside and window_lives == 0.0),
            "population_identity": bool(window_identity),
            "method": (
                "Normal bins inside SimulationParams age_min..age_max, "
                "renormalised to the population. The simulator keeps a draw "
                "only inside that window."
            ),
        },
        "open_normal": {
            "lives": round(open_lives, 6),
            "mass_ages_0_to_120": round(open_mass, 4),
            "incidence_lives": _portion(incidence_num, incidence_den, incidence_missing),
            "incidence_ages_withheld": incidence_missing,
            "incidence_withheld_lives": round(incidence_missing_mass, 8),
            "portfolio_adl_3_lives": _portion(mix3_num, mix3_den, mix3_missing),
            "portfolio_adl_3_ages_withheld": mix3_missing,
            "portfolio_adl_3_withheld_lives": round(mix3_missing_mass, 8),
            "decline_threshold_lives": _portion(decline_num, decline_den, decline_missing),
            "decline_ages_withheld": decline_missing,
            "decline_withheld_lives": round(decline_missing_mass, 8),
            "expectancy": {
                "basis": basis,
                "average_years": avg,
                "male_years": male_w,
                "female_years": female_w,
                "healthy_curtate_years": healthy_w,
                "ages_withheld": sorted(set(avg_missing + male_missing + female_missing + healthy_missing)),
                "source": "adl3_disabled_life_expectancy",
                "healthy_source": "curtate_life_expectancy on mortality q(x)",
            },
            "at_age_floor": {
                "age": floor,
                "average_years": None if floor_row is None else floor_row.get("average_years"),
                "male_years": None if floor_row is None else floor_row.get("male_years"),
                "female_years": None if floor_row is None else floor_row.get("female_years"),
                "healthy_curtate_years": floor_healthy,
                "disability_incidence_per_life": _rate_per_life(
                    tables, "disability_incidence_rates", floor
                ),
            },
            "rows": detailed[:48],
            "rows_truncated": len(detailed) > 48,
            "method": (
                "Continuity-corrected normal bin from services.actuarial_service._normal_bin_count. "
                "ADL incidence is the disability table i(x) for that age. "
                "ADL 3 years are the published row, count-weighted. "
                "They are not q(x) times a mortality multiplier."
            ),
        },
        "decades": decades,
        "integrity_checks": {
            "portfolio_window_sums_to_population": bool(window_identity),
            "open_tail_not_negative": open_lives >= -1e-9 and window_lives >= -1e-9,
            "decades_cover_open_mass": abs(decade_sum - round(open_mass, 4)) <= 0.05,
            "missing_expectancy_not_zeroed": True,
            "formula_id": FORMULA_ID,
        },
    }


def _fmt_exact(value: Optional[float]) -> str:
    """Comma-grouped text of the same token ``json.dumps`` would emit."""
    if value is None:
        return "withheld"
    raw = json.dumps(value)
    # json.dumps emits 1e-05 with no decimal point. int() cannot parse that.
    if "e" in raw or "E" in raw:
        return raw
    if "." not in raw:
        return f"{int(raw):,}"
    whole, frac = raw.split(".", 1)
    return f"{int(whole):,}.{frac}"


def _fmt_lives(value: Optional[float]) -> str:
    return _fmt_exact(value)


def _fmt_years(value: Optional[float]) -> str:
    return _fmt_exact(value)


def _year_field(sex: str) -> str:
    if sex == "male":
        return "male_years"
    if sex == "female":
        return "female_years"
    return "average_years"


def _adl_phrase(basis: str, lang: str) -> str:
    phrases = {
        "incidence": ("one-year disability incidence i(x)", "היארעות נכות לשנה אחת i(x)"),
        "portfolio_adl_3": ("portfolio mix at ADL 3 or higher", "תמהיל התיק ב-ADL 3 ומעלה"),
        "decline_threshold": ("portfolio mix at the decline threshold or higher", "תמהיל התיק בסף הדחייה ומעלה"),
    }
    return phrases[basis][0 if lang == "en" else 1]


def _withheld_ages(facts: Mapping[str, Any]) -> List[int]:
    basis = facts["applied"]["adl_basis"]
    open_n = facts["open_normal"]
    if basis == "portfolio_adl_3":
        ages = open_n.get("portfolio_adl_3_ages_withheld") or []
    elif basis == "decline_threshold":
        ages = open_n.get("decline_ages_withheld") or []
    else:
        ages = open_n.get("incidence_ages_withheld") or []
    return [int(age) for age in ages]


def _adl_value(facts: Mapping[str, Any]) -> Optional[float]:
    basis = facts["applied"]["adl_basis"]
    open_n = facts["open_normal"]
    if basis == "portfolio_adl_3":
        return open_n.get("portfolio_adl_3_lives")
    if basis == "decline_threshold":
        return open_n.get("decline_threshold_lives")
    return open_n.get("incidence_lives")


def cohort_copy(facts: Mapping[str, Any]) -> Dict[str, str]:
    applied = facts["applied"]
    standard = facts["standard"]
    window = facts["portfolio_window"]
    open_n = facts["open_normal"]
    floor_row = open_n["at_age_floor"]
    sex = applied["sex"]
    year_key = _year_field(sex)
    weighted_years = open_n["expectancy"].get(year_key)
    floor_years = floor_row.get(year_key if year_key != "healthy_curtate_years" else "average_years")
    if year_key == "average_years":
        floor_years = floor_row.get("average_years")
    elif year_key == "male_years":
        floor_years = floor_row.get("male_years")
    else:
        floor_years = floor_row.get("female_years")
    lives_w = _fmt_lives(window["lives"])
    lives_o = _fmt_lives(open_n["lives"])
    adl = _fmt_lives(_adl_value(facts))
    view = applied.get("distribution") or "both"
    if view == "portfolio_window":
        view_en = f" This view leads with the portfolio window ({lives_w} lives)."
        view_he = f" תצוגה זו מובילה בחלון התיק ({lives_w} חיים)."
    elif view == "open_normal":
        view_en = f" This view leads with the open normal ({lives_o} lives)."
        view_he = f" תצוגה זו מובילה בנורמלית הפתוחה ({lives_o} חיים)."
    else:
        view_en = " Both the portfolio window and the open normal are in this view."
        view_he = " חלון התיק והנורמלית הפתוחה שניהם בתצוגה הזו."
    missing_ages = _withheld_ages(facts)
    if missing_ages:
        listed = ", ".join(str(age) for age in missing_ages[:12])
        age_word = "Age" if len(missing_ages) == 1 else "Ages"
        age_word_he = "לגיל" if len(missing_ages) == 1 else "לגילים"
        gap_en = (
            f" {age_word} {listed} has no published rate for that measure, "
            "so those lives are excluded from that count."
            if len(missing_ages) == 1 else
            f" Ages {listed} have no published rate for that measure, "
            "so those lives are excluded from that count."
        )
        gap_he = (
            f" {age_word_he} {listed} אין שיעור מפורסם למדד הזה, "
            "ולכן החיים האלה אינם נכללים בספירה."
        )
    else:
        gap_en = ""
        gap_he = ""
    years_person = _fmt_years(floor_years)
    years_weighted = _fmt_years(weighted_years)
    healthy = _fmt_years(floor_row.get("healthy_curtate_years"))
    male = _fmt_years(floor_row.get("male_years"))
    female = _fmt_years(floor_row.get("female_years"))
    scenario = ""
    scenario_he = ""
    if applied.get("scenario"):
        scenario = (
            f" This is a scenario. The unmodified standard draw is mean {standard['mean']}, "
            f"sd {standard['std']}, ages {standard['age_min']}–{standard['age_max']}."
        )
        scenario_he = (
            f" זו תרחיש. ההגרלה הסטנדרטית ללא שינוי היא ממוצע {standard['mean']}, "
            f"סטיית תקן {standard['std']}, גילים {standard['age_min']}–{standard['age_max']}."
        )
    outside = ""
    outside_he = ""
    if window.get("outside_draw_window"):
        outside = (
            f" Age {applied['age_floor']}+ is outside the standard draw window "
            f"{applied['age_min']}–{applied['age_max']}, so that count is zero there."
        )
        outside_he = (
            f" גיל {applied['age_floor']}+ נמצא מחוץ לחלון ההגרלה "
            f"{applied['age_min']}–{applied['age_max']}, ולכן הספירה שם היא אפס."
        )
    en = (
        f"Of {applied['population']:,} lives on the standard normal "
        f"(mean {applied['mean']}, sd {applied['std']}), "
        f"the portfolio window expects {lives_w} lives aged {applied['age_floor']}+ "
        f"and the open normal expects {lives_o}.{outside} "
        f"On the open normal, {_adl_phrase(applied['adl_basis'], 'en')} "
        f"accounts for {adl} lives.{gap_en} "
        f"A person aged {applied['age_floor']} has published ADL 3 remaining life of "
        f"{years_person} years (man {male}, woman {female}) and healthy curtate life of "
        f"{healthy} years. The count-weighted figure on that tail is {years_weighted} years."
        f"{view_en}{scenario}"
    )
    he = (
        f"מתוך {applied['population']:,} חיים בהתפלגות הנורמלית הסטנדרטית "
        f"(ממוצע {applied['mean']}, סטיית תקן {applied['std']}), "
        f"חלון התיק צופה {lives_w} חיים בגיל {applied['age_floor']}+ "
        f"והנורמלית הפתוחה צופה {lives_o}.{outside_he} "
        f"בנורמלית הפתוחה, {_adl_phrase(applied['adl_basis'], 'he')} "
        f"מסבירה {adl} חיים.{gap_he} "
        f"לאדם בגיל {applied['age_floor']} תוחלת שנותרה לפי ADL 3 היא "
        f"{years_person} שנים (גבר {male}, אישה {female}) ותוחלת בריאה מקוצרת היא "
        f"{healthy} שנים. הממוצע המשוקלל בזנב הזה הוא {years_weighted} שנים."
        f"{view_he}{scenario_he}"
    )
    return {"en": en, "he": he}


def _classify(question: str) -> str:
    q = (question or "").casefold()
    has_customer = bool(_CUST_ID.search(question or "")) or bool(_EMAIL.search(question or ""))
    customer_words = any(word in q for word in (
        "customer report", "full report", "report about", "report on", "דוח לקוח", "דוח על לקוח",
    ))
    cohort = any((
        re.search(r"\d+\s*\+", q),
        "age distribution" in q,
        "standard age" in q,
        "life expectancy" in q,
        "expected to live" in q,
        "for how many years" in q,
        "can be adl" in q,
        "התפלגות" in q,
        "תוחלת" in q,
    ))
    if has_customer or (customer_words and not cohort):
        return "customer_report"
    if cohort:
        return "cohort_adl"
    if _SIM_ID.search(question or "") or any(word in q for word in (
        "recent simulation", "specific simulation", "latest simulation", "סימולציה אחרונה",
    )):
        return "simulation"
    if any(word in q for word in (
        "what if", "design a", "new product", "change the", "optimize", "forecast profit",
        "תכנן", "מה אם",
    )):
        return "planning"
    if any(word in q for word in (
        "activate media", "open media", "media feature", "storyboard", "video agent", "מדיה",
    )):
        return "media"
    if any(word in q for word in (
        "every dashboard", "all dashboards", "list dashboard", "which dashboard", "דשבורד",
    )):
        return "dashboards"
    if any(word in q for word in ("balance sheet", "ledger", "מאזן", "ספר חשבונות")):
        return "ledger"
    if any(word in q for word in ("underwriting issue", "pending underwriting", "חיתום")):
        return "underwriting"
    if any(word in q for word in ("claims issue", "open claim", "pending claim", "תביע")):
        return "claims"
    if any(word in q for word in ("how many customer", "how many policies", "book snapshot", "כמה לקוח")):
        return "book"
    return "book"


def _planning_for(question: str) -> Optional[Dict[str, Any]]:
    q = (question or "").casefold()
    if any(word in q for word in ("monte carlo", "מונטה")):
        agent = "monte_carlo_evaluation"
        url = "/admin.html"
        action = "run_monte_carlo_evaluation"
        name = ("Monte Carlo evaluation", "הערכת מונטה קרלו")
    elif any(word in q for word in ("underwriting file", "assess this life", "הערכת סיכון")):
        agent = "assessment_center"
        url = "/assessment-center.html"
        action = None
        name = ("Assessment center", "מרכז הערכה")
    else:
        agent = "portfolio_simulator"
        url = "/actuary-dashboard.html"
        action = "run_actuary_simulation"
        name = ("Portfolio simulator", "סימולטור התיק")
    return {
        "needs_planning": True,
        "suggested_agent": agent,
        "name_en": name[0],
        "name_he": name[1],
        "url": url,
        "client_action": action,
        "reason_en": (
            "This question is not answered by a stored row or a published formula. "
            "The desk does not estimate it. Open the named tool; a high-impact run stays confirmation-gated."
        ),
        "reason_he": (
            "השאלה הזו אינה נענית משורה שמורה או מנוסחה מפורסמת. "
            "השולחן אינו אומד אותה. פתחו את הכלי שצוין. הרצה כבדה נשארת מאחורי אישור."
        ),
    }


def _census(books: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not books:
        return {"available": False}
    counts = {}
    for key in ("customers", "policies", "claims", "underwriting", "billing", "ledger"):
        value = books.get(key)
        try:
            counts[key] = None if value is None else len(value)
        except TypeError:
            counts[key] = None
    counts["available"] = True
    return counts


def _redact_key(key: str) -> bool:
    name = str(key).lower()
    if name in _KEEP_KEYS:
        return False
    if name in _REDACT_KEYS:
        return True
    return any(part in name for part in ("password", "secret", "token", "cvv", "card_number", "ssn"))


def _redact(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return None
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if _redact_key(str(key)):
                cleaned[str(key)] = "[redacted]"
            else:
                cleaned[str(key)] = _redact(item, depth + 1)
        return cleaned
    if isinstance(value, list):
        return [_redact(item, depth + 1) for item in value[:20]]
    if isinstance(value, str) and len(value) > 400:
        return value[:400]
    return value


def _known_age(dob: Any) -> Optional[int]:
    """Age from a stored date of birth. A missing date stays None, not 35."""
    if not dob:
        return None
    text = str(dob)[:10]
    try:
        born = datetime.fromisoformat(text).date()
    except ValueError:
        return None
    today = datetime.now(timezone.utc).date()
    years = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    if years < 0 or years > 120:
        return None
    return years


def _customer_name(row: Mapping[str, Any]) -> str:
    named = row.get("name") or row.get("full_name")
    if named:
        return str(named)
    parts = [row.get("first_name"), row.get("last_name")]
    return " ".join(str(part) for part in parts if part)


def _find_customers(question: str, customers: Mapping[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    wanted_ids = {match.group(1).upper() for match in _CUST_ID.finditer(question or "")}
    wanted_email = {match.group(1).casefold() for match in _EMAIL.finditer(question or "")}
    quoted = re.findall(r"[\"']([^\"']{2,80})[\"']", question or "")
    hits = []
    for key, row in customers.items():
        if not isinstance(row, dict):
            continue
        ident = str(row.get("customer_id") or row.get("id") or key)
        name = _customer_name(row)
        email = str(row.get("email") or "").casefold()
        if ident.upper() in wanted_ids or str(key).upper() in wanted_ids:
            hits.append((ident, row))
            continue
        if email and email in wanted_email:
            hits.append((ident, row))
            continue
        if any(fragment.casefold() in name.casefold() and len(fragment.strip()) > 1 for fragment in quoted):
            hits.append((ident, row))
    return hits[:8]


def _rows_for(store: Optional[Mapping[str, Any]], customer_id: str, fields: Sequence[str],
              limit: int = 12) -> List[Dict[str, Any]]:
    rows = []
    for key, row in (store or {}).items():
        if not isinstance(row, dict):
            continue
        if str(row.get("customer_id") or "") != str(customer_id):
            continue
        item = {"id": str(row.get("id") or key)}
        for field in fields:
            if field in row:
                item[field] = row.get(field)
        rows.append(_redact(item))
        if len(rows) >= limit:
            break
    return rows


def _customer_facts(question: str, books: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    customers = (books or {}).get("customers") or {}
    if not customers:
        return {"matched": 0, "withheld": "customer book is not loaded"}
    hits = _find_customers(question, customers)
    if not hits:
        return {
            "matched": 0,
            "withheld": "no customer matched that id, email, or quoted name",
            "census": _census(books),
        }
    if len(hits) > 1 and not _CUST_ID.search(question or ""):
        return {
            "matched": len(hits),
            "candidates": [
                {"customer_id": ident, "name": _customer_name(row), "email": row.get("email")}
                for ident, row in hits
            ],
            "withheld": "more than one customer matched; repeat the question with the customer id",
        }
    ident, row = hits[0]
    profile = _redact(dict(row))
    policies = _rows_for(books.get("policies"), ident, (
        "status", "policy_id", "annual_premium", "coverage_amount", "product", "adl_level",
    ))
    claims = _rows_for(books.get("claims"), ident, (
        "status", "claimed_amount", "approved_amount", "paid_amount", "policy_id", "adl_level",
    ))
    underwriting = _rows_for(books.get("underwriting"), ident, (
        "status", "adl_level", "decision", "risk_score",
    ))
    billing = _rows_for(books.get("billing"), ident, (
        "status", "amount_due", "amount_paid", "amount", "policy_id",
    ))
    ledger = _rows_for(books.get("ledger"), ident, (
        "type", "transaction_type", "amount", "status", "created_at",
    ), limit=20)
    age = _known_age(row.get("dob") or row.get("date_of_birth"))
    projection: Dict[str, Any] = {"withheld": "date of birth is not on the customer record"}
    if age is not None and books is not None:
        try:
            from services.financial_reporting_service import get_financial_reporting_service
            service = get_financial_reporting_service(
                books.get("policies") or {},
                books.get("claims") or {},
                books.get("billing") or {},
                books.get("customers") or {},
                books.get("underwriting") or {},
                books.get("ledger"),
            )
            raw = service.generate_customer_projection(ident, age=age)
            projection = {
                "age": age,
                "scenario": raw.get("scenario"),
                "premium_breakdown": raw.get("premium_breakdown"),
                "key_milestones": raw.get("key_milestones"),
            }
        except Exception:
            projection = {"withheld": "customer projection did not resolve from the stored policy", "age": age}
    return {
        "matched": 1,
        "customer_id": ident,
        "profile": profile,
        "policies": policies,
        "claims": claims,
        "underwriting": underwriting,
        "billing": billing,
        "ledger": ledger,
        "projection": projection,
        "plaintext_id_removed": any(_redact_key(str(key)) for key in row.keys()),
    }


def _issue_rows(store: Optional[Mapping[str, Any]], open_statuses: Iterable[str],
                fields: Sequence[str]) -> Dict[str, Any]:
    wanted = {status.lower() for status in open_statuses}
    rows = []
    total = 0
    for key, row in (store or {}).items():
        if not isinstance(row, dict):
            continue
        status = str(row.get("status") or "").lower().replace(" ", "_")
        if status not in wanted:
            continue
        total += 1
        if len(rows) < 12:
            item = {"id": str(row.get("id") or key), "status": row.get("status"),
                    "customer_id": row.get("customer_id")}
            for field in fields:
                if field in row:
                    item[field] = row.get(field)
            rows.append(_redact(item))
    return {"count": total, "sample": rows}


def _book_facts(books: Optional[Mapping[str, Any]], kinds: Sequence[str]) -> Dict[str, Any]:
    facts: Dict[str, Any] = {"census": _census(books)}
    if not books:
        facts["withheld"] = "books were not passed to the desk"
        return facts
    try:
        from services.financial_reporting_service import get_financial_reporting_service
        service = get_financial_reporting_service(
            books.get("policies") or {},
            books.get("claims") or {},
            books.get("billing") or {},
            books.get("customers") or {},
            books.get("underwriting") or {},
            books.get("ledger"),
        )
    except Exception:
        facts["withheld"] = "financial reporting service did not load"
        return facts
    summaries = {}
    for kind in kinds:
        try:
            summaries[kind] = service.get_dashboard_summary(kind)
        except Exception:
            summaries[kind] = {"withheld": f"{kind} summary failed"}
    facts["summaries"] = summaries
    if "admin" in kinds:
        try:
            portfolio = service.generate_portfolio_report()
            facts["portfolio_summary"] = portfolio.get("summary")
            facts["portfolio_age_distribution"] = portfolio.get("age_distribution")
        except Exception:
            facts["portfolio_summary"] = {"withheld": "portfolio report failed"}
    return facts


def _summarize_simulation(sim: Mapping[str, Any], age_floor: Optional[int]) -> Dict[str, Any]:
    matrix = sim.get("age_adl_matrix") or {}
    distribution = matrix.get("distribution") or {}
    histogram = distribution.get("histogram") or []
    band = {"applied": 0, "accepted": 0, "rejected": 0}
    if age_floor is not None:
        for row in histogram:
            if not isinstance(row, dict):
                continue
            try:
                age = int(row.get("age"))
            except (TypeError, ValueError):
                continue
            if age < int(age_floor):
                continue
            band["applied"] += int(row.get("applied") or 0)
            band["accepted"] += int(row.get("accepted") or 0)
            band["rejected"] += int(row.get("rejected") or 0)
    sample = (distribution.get("sample") or {}) if isinstance(distribution, dict) else {}
    integrity = (matrix.get("integrity") or {}) if isinstance(matrix, dict) else {}
    return {
        "simulation_id": sim.get("simulation_id"),
        "run_at": sim.get("run_at"),
        "tables_version": sim.get("tables_version"),
        "parameters": {
            key: (sim.get("parameters") or {}).get(key)
            for key in (
                "customer_count", "age_min", "age_max", "age_mean", "age_std", "age_distribution",
            )
        },
        "portfolio_summary": sim.get("portfolio_summary"),
        "sample": sample,
        "matrix_totals": matrix.get("totals"),
        "matrix_integrity_pass": (integrity.get("all_checks_pass") if isinstance(integrity, dict) else None),
        "lives_at_or_above_floor": None if age_floor is None else band,
        "priced_lives_omitted": "priced_lives" in sim or "declined_sample" in sim,
    }


def _simulation_facts(question: str, simulations: Optional[Sequence[Mapping[str, Any]]],
                      age_floor: Optional[int]) -> Dict[str, Any]:
    rows = [sim for sim in (simulations or []) if isinstance(sim, Mapping)]
    wanted = {match.group(1).upper() for match in _SIM_ID.finditer(question or "")}
    if wanted:
        rows = [sim for sim in rows if str(sim.get("simulation_id") or "").upper() in wanted]
    if not rows:
        return {
            "matched": 0,
            "withheld": "no stored simulation matched; a new draw is not started from this desk",
        }
    rows_sorted = sorted(rows, key=lambda sim: str(sim.get("run_at") or ""), reverse=True)
    return {
        "matched": len(rows_sorted),
        "reports": [_summarize_simulation(sim, age_floor) for sim in rows_sorted[:5]],
    }


def _variant_schema() -> List[Dict[str, Any]]:
    return [
        {"key": "population", "type": "int", "min": 1, "max": 10000000, "label_en": "Lives", "label_he": "חיים"},
        {"key": "age_floor", "type": "int", "min": 0, "max": 120, "label_en": "Age floor", "label_he": "גיל מינימום"},
        {"key": "age_cap", "type": "int", "min": 0, "max": 120, "label_en": "Age cap", "label_he": "גיל מקסימום"},
        {"key": "mean", "type": "number", "min": 0, "max": 120, "label_en": "Mean age", "label_he": "גיל ממוצע"},
        {"key": "std", "type": "number", "min": 0.01, "max": 40, "label_en": "Age sd", "label_he": "סטיית תקן"},
        {"key": "age_min", "type": "int", "min": 0, "max": 120, "label_en": "Draw from", "label_he": "הגרלה מגיל"},
        {"key": "age_max", "type": "int", "min": 0, "max": 120, "label_en": "Draw to", "label_he": "הגרלה עד גיל"},
        {"key": "distribution", "type": "enum", "values": ["both", "open_normal", "portfolio_window"],
         "label_en": "Distribution view", "label_he": "תצוגת התפלגות"},
        {"key": "sex", "type": "enum", "values": ["average", "male", "female"],
         "label_en": "Remaining-life column", "label_he": "עמודת תוחלת"},
        {"key": "adl_basis", "type": "enum",
         "values": ["incidence", "portfolio_adl_3", "decline_threshold"],
         "label_en": "ADL measure", "label_he": "מדד ADL"},
    ]


def _affiliated(intent: str, applied: Mapping[str, Any]) -> List[Dict[str, Any]]:
    items = []
    if intent == "cohort_adl":
        floor = int(applied["age_floor"])
        items.append({
            "label_en": "Portfolio window",
            "label_he": "חלון התיק",
            "variants": {"distribution": "portfolio_window"},
        })
        items.append({
            "label_en": "Open normal",
            "label_he": "נורמלית פתוחה",
            "variants": {"distribution": "open_normal"},
        })
        other = max(0, floor - 10)
        items.append({
            "label_en": f"Age {other}+",
            "label_he": f"גיל {other}+",
            "variants": {"age_floor": other},
        })
    items.append({
        "label_en": "Current book",
        "label_he": "הספר הנוכחי",
        "question": "book snapshot of customers policies claims underwriting and the ledger",
    })
    items.append({
        "label_en": "Dashboards",
        "label_he": "לוחות",
        "question": "list every dashboard",
    })
    return items


def _copy_pair(en: str, he: str) -> Dict[str, str]:
    return {"en": en, "he": he}


def _maybe_narrate(copy: Dict[str, str], facts: Mapping[str, Any], lang: str,
                   narrate: bool, provider: Any) -> Dict[str, Any]:
    narrative = {"source": "deterministic", "fallback_reason": None, "lang": lang}
    if not narrate:
        return narrative
    if provider is None:
        try:
            from services.llm_providers import get_llm_provider
            provider = get_llm_provider()
        except Exception:
            narrative["fallback_reason"] = "llm_unavailable"
            return narrative
    try:
        from services.llm_providers import LLMUnavailableError
    except Exception:
        LLMUnavailableError = Exception  # type: ignore
    allowed = numbers_in(facts)
    system = (
        "You rephrase an insurance answer. Use only numbers that already appear in FACTS. "
        "Do not add, round, or invent a figure. Return one paragraph."
    )
    user = "FACTS:\n" + _canonical(facts) + "\n\nANSWER:\n" + (copy.get(lang) or copy["en"])
    try:
        text = provider.completion(system, user)
    except LLMUnavailableError:
        narrative["fallback_reason"] = "llm_unavailable"
        return narrative
    except Exception:
        narrative["fallback_reason"] = "llm_failed"
        return narrative
    extra = numbers_in(str(text)) - allowed
    if extra:
        narrative["fallback_reason"] = "narrative_introduced_numbers"
        narrative["rejected_numbers"] = sorted(extra)
        return narrative
    copy[lang] = str(text).strip()
    narrative["source"] = "llm"
    return narrative


def answer_query(
    question: str,
    *,
    books: Optional[Mapping[str, Any]] = None,
    simulations: Optional[Sequence[Mapping[str, Any]]] = None,
    tables: Optional[Mapping[str, Any]] = None,
    config: Any = None,
    variants: Optional[Mapping[str, Any]] = None,
    lang: str = "en",
    narrate: bool = False,
    provider: Any = None,
    actor_role: str = "",
) -> Dict[str, Any]:
    """Build one sealed report. The books mapping is not modified."""
    text = str(question or "").strip()
    if not text:
        raise AdminAIBiError("Enter a question")
    if lang not in ("en", "he"):
        lang = "he" if _HEBREW.search(text) else "en"
    elif _HEBREW.search(text) and lang == "en" and not variants:
        lang = "he"
    intent = _classify(text)
    applied = resolve_variants(text, variants)
    loaded_tables, loaded_config, tables_version = _load_tables(tables, config)
    facts: Dict[str, Any] = {"census": _census(books)}
    planning = None
    client_action = None
    if intent == "cohort_adl":
        facts.update(build_cohort(applied, loaded_tables, loaded_config, tables_version))
        copy = cohort_copy(facts)
    elif intent == "customer_report":
        facts["customer"] = _customer_facts(text, books)
        matched = facts["customer"].get("matched")
        if matched == 1:
            ident = facts["customer"]["customer_id"]
            projection = facts["customer"].get("projection") or {}
            premium = (projection.get("premium_breakdown") or {}).get("annual_premium")
            premium_en = ""
            premium_he = ""
            if isinstance(premium, (int, float)):
                shown = _fmt_exact(premium)
                premium_en = f" Stored-policy annual premium in the projection is {shown}."
                premium_he = f" הפרמיה השנתית בהקרנה לפי הפוליסה השמורה היא {shown}."
            copy = _copy_pair(
                f"Customer {ident}: {len(facts['customer']['policies'])} policies, "
                f"{len(facts['customer']['claims'])} claims, "
                f"{len(facts['customer']['underwriting'])} underwriting rows, "
                f"{len(facts['customer']['billing'])} bills in this extract.{premium_en}",
                f"לקוח {ident}: {len(facts['customer']['policies'])} פוליסות, "
                f"{len(facts['customer']['claims'])} תביעות, "
                f"{len(facts['customer']['underwriting'])} שורות חיתום, "
                f"{len(facts['customer']['billing'])} חיובים בקטע הזה.{premium_he}",
            )
        else:
            reason = facts["customer"].get("withheld") or "no customer selected"
            copy = _copy_pair(reason, reason)
    elif intent == "simulation":
        floor = _parse_age_floor(text)
        facts["simulations"] = _simulation_facts(text, simulations, floor)
        if facts["simulations"].get("matched"):
            first = facts["simulations"]["reports"][0]
            copy = _copy_pair(
                f"Stored simulation {first.get('simulation_id')} is summarised from the saved run. "
                "Priced-life rows are omitted.",
                f"הסימולציה השמורה {first.get('simulation_id')} מסוכמת מהריצה שנשמרה. "
                "שורות החיים המתומחרים הושמטו.",
            )
        else:
            planning = _planning_for(text)
            copy = _copy_pair(planning["reason_en"], planning["reason_he"])
    elif intent == "planning":
        planning = _planning_for(text)
        facts["book"] = _book_facts(books, ("admin",))
        copy = _copy_pair(planning["reason_en"], planning["reason_he"])
    elif intent == "media":
        generate = any(word in text.casefold() for word in ("generate", "queue", "הפק"))
        client_action = {
            "kind": "confirm_action" if generate else "navigate",
            "action_id": "batch_generate_marketing_videos" if generate else None,
            "url": "/admin-media.html",
            "mutate": False,
        }
        copy = _copy_pair(
            "Media jobs are not started from this report. Open the media desk. "
            "A generate request stays on the confirmation-gated mic action.",
            "משימות מדיה אינן נפתחות מהדוח הזה. פתחו את שולחן המדיה. "
            "בקשת הפקה נשארת על פעולת המיקרופון שדורשת אישור.",
        )
    elif intent == "dashboards":
        copy = _copy_pair(
            "Every linked dashboard is listed in this report. Pages for another role stay named and are not opened as the admin book.",
            "כל לוח מקושר מופיע בדוח הזה. עמוד של תפקיד אחר נשאר בשמו ואינו נפתח כספר המנהל.",
        )
    elif intent == "ledger":
        facts["book"] = _book_facts(books, ("accountant", "admin"))
        copy = _copy_pair(
            "Ledger and accountant figures are the financial reporting summaries of the current books.",
            "נתוני הספר והחשבונאות הם סיכומי הדיווח הכספי של הספרים הנוכחיים.",
        )
    elif intent == "underwriting":
        facts["issues"] = _issue_rows(
            (books or {}).get("underwriting"),
            ("pending", "referred", "manual_review", "under_review"),
            ("adl_level", "risk_score"),
        )
        facts["book"] = _book_facts(books, ("underwriter",))
        copy = _copy_pair(
            f"Open underwriting rows in this extract: {facts['issues']['count']}.",
            f"שורות חיתום פתוחות בקטע הזה: {facts['issues']['count']}.",
        )
    elif intent == "claims":
        facts["issues"] = _issue_rows(
            (books or {}).get("claims"),
            ("pending", "under_review", "medical_assessment", "approved"),
            ("claimed_amount", "approved_amount"),
        )
        facts["book"] = _book_facts(books, ("claims",))
        copy = _copy_pair(
            f"Open claim rows in this extract: {facts['issues']['count']}.",
            f"שורות תביעה פתוחות בקטע הזה: {facts['issues']['count']}.",
        )
    else:
        facts["book"] = _book_facts(books, ("admin", "underwriter", "claims", "accountant"))
        census = facts["census"]
        copy = _copy_pair(
            "Book census from the stores attached to this desk: "
            f"customers {census.get('customers')}, policies {census.get('policies')}, "
            f"claims {census.get('claims')}, underwriting {census.get('underwriting')}.",
            "מפקד הספר מהמחסנים המחוברים לשולחן הזה: "
            f"לקוחות {census.get('customers')}, פוליסות {census.get('policies')}, "
            f"תביעות {census.get('claims')}, חיתום {census.get('underwriting')}.",
        )
    if intent != "cohort_adl":
        facts["applied"] = applied
        facts["tables_version"] = tables_version
    narrative = _maybe_narrate(copy, facts, lang, narrate, provider)
    catalog = dashboard_catalog()
    seal_body = {"question": text, "intent": intent, "facts": facts}
    report = {
        "report_id": "AIBI-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(4),
        "question": text,
        "intent": intent,
        "lang": lang,
        "generated_at": _now(),
        "actor_role": str(actor_role or ""),
        "answer": copy,
        "facts": facts,
        "variants": {"applied": applied, "schema": _variant_schema()},
        "affiliated": _affiliated(intent, applied),
        "dashboards": catalog,
        "client_action": client_action,
        "planning": planning,
        "narrative": narrative,
        "integrity": {
            "formula_id": FORMULA_ID,
            "read_only": True,
            "side_effects": [],
            "facts_sha256": _sha256(seal_body),
            "tables_version": tables_version,
            "plaintext_national_id_returned": False,
        },
    }
    return remember_report(report)


def remember_report(report: Dict[str, Any]) -> Dict[str, Any]:
    with _LOCK:
        _REPORTS[report["report_id"]] = copy.deepcopy(report)
        while len(_REPORTS) > _MAX_REPORTS:
            _REPORTS.popitem(last=False)
    return report


def get_report(report_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        stored = _REPORTS.get(str(report_id or ""))
    return None if stored is None else copy.deepcopy(stored)


def clear_reports() -> None:
    """Test helper. Production callers do not reset the desk."""
    with _LOCK:
        _REPORTS.clear()


def _md_escape(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|")


def render_markdown(report: Mapping[str, Any], lang: str = "en") -> str:
    lang = "he" if lang == "he" else "en"
    answer = (report.get("answer") or {}).get(lang) or (report.get("answer") or {}).get("en") or ""
    lines = [
        f"# PHINS admin report {report.get('report_id')}",
        "",
        "PHINS — Personal Health Insurance & Savings",
        "",
        answer,
        "",
        f"Question: {report.get('question')}",
        f"Intent: {report.get('intent')}",
        f"Seal: {(report.get('integrity') or {}).get('facts_sha256')}",
        f"Formula: {(report.get('integrity') or {}).get('formula_id')}",
        "",
    ]
    facts = report.get("facts") or {}
    open_n = facts.get("open_normal") or {}
    rows = open_n.get("rows") or []
    if rows:
        lines.append("| age | lives | i(x) | ADL 3 years | healthy years |")
        lines.append("| --- | --- | --- | --- | --- |")
        for row in rows:
            lines.append(
                "| {age} | {lives} | {ix} | {years} | {healthy} |".format(
                    age=_md_escape(row.get("age")),
                    lives=_md_escape(row.get("lives")),
                    ix=_md_escape(row.get("disability_incidence_per_life")),
                    years=_md_escape(row.get("adl3_average_years")),
                    healthy=_md_escape(row.get("healthy_curtate_years")),
                )
            )
        lines.append("")
    decades = facts.get("decades") or []
    if decades:
        lines.append("| age band | lives |")
        lines.append("| --- | --- |")
        for row in decades:
            lines.append(f"| {row.get('age_min')}-{row.get('age_max')} | {row.get('lives')} |")
        lines.append("")
    lines.append("## Dashboards")
    lines.append("")
    for row in report.get("dashboards") or []:
        if not row.get("admin_open"):
            continue
        label = row.get("label_he") if lang == "he" else row.get("label_en")
        lines.append(f"- {label}: {row.get('path')}")
    if report.get("planning"):
        lines.append("")
        lines.append((report["planning"].get("reason_he") if lang == "he" else report["planning"].get("reason_en")) or "")
    return "\n".join(lines).rstrip() + "\n"


def _esc(value: Any) -> str:
    import html as html_lib
    return html_lib.escape(str(value if value is not None else ""))


def _metric_grid(items: Sequence[Tuple[str, Any]]) -> str:
    shown = [(label, value) for label, value in items if value is not None and value != ""]
    if not shown:
        return ""
    cells = "".join(
        "<div class=\"metric\"><strong>{value}</strong><span>{label}</span></div>".format(
            value=_esc(value), label=_esc(label),
        )
        for label, value in shown
    )
    return "<div class=\"metric-grid\">" + cells + "</div>"


def _document_metrics(facts: Mapping[str, Any], lang: str) -> str:
    he = lang == "he"
    window = facts.get("portfolio_window") or {}
    open_n = facts.get("open_normal") or {}
    floor = open_n.get("at_age_floor") or {}
    items: List[Tuple[str, Any]] = []
    if isinstance(window, Mapping) and "lives" in window:
        items.append(("חלון התיק" if he else "Portfolio window", window.get("lives")))
    if isinstance(open_n, Mapping) and "lives" in open_n:
        items.append(("נורמלית פתוחה" if he else "Open normal", open_n.get("lives")))
        items.append(("היארעות נכות" if he else "Disability incidence", open_n.get("incidence_lives")))
    if isinstance(floor, Mapping):
        items.append(("ADL 3 בגיל הרצפה" if he else "ADL 3 at the age floor", floor.get("average_years")))
        items.append(("תוחלת בריאה" if he else "Healthy curtate years", floor.get("healthy_curtate_years")))
    customer = facts.get("customer") or {}
    if isinstance(customer, Mapping) and customer.get("customer_id"):
        items.append(("לקוח" if he else "Customer", customer.get("customer_id")))
    return _metric_grid(items)


def render_html(report: Mapping[str, Any], lang: str = "en") -> str:
    from services.phins_document import render_phins_document

    lang = "he" if lang == "he" else "en"
    he = lang == "he"
    answer = (report.get("answer") or {}).get(lang) or (report.get("answer") or {}).get("en") or ""
    facts = report.get("facts") or {}
    body = [
        "<p class=\"sub\">{}</p>".format(_esc(report.get("question") or "")),
        "<p class=\"note\">{}</p>".format(_esc(answer)),
        _document_metrics(facts, lang),
    ]
    planning = report.get("planning") or {}
    if planning:
        reason = planning.get("reason_he") if he else planning.get("reason_en")
        name = planning.get("name_he") if he else planning.get("name_en")
        body.append("<div class=\"summary-box\"><strong>{}</strong><p>{}</p></div>".format(
            _esc(name or ""), _esc(reason or ""),
        ))
    rows = (facts.get("open_normal") or {}).get("rows") or []
    if rows:
        heads = (
            ("גיל", "חיים", "i(x)", "שנות ADL 3", "שנים בריאות")
            if he else
            ("Age", "Lives", "i(x)", "ADL 3 years", "Healthy years")
        )
        body.append("<h2>{}</h2>".format("גילאים בזנב" if he else "Ages in the tail"))
        body.append("<table><thead><tr>" + "".join("<th>{}</th>".format(_esc(head)) for head in heads) + "</tr></thead><tbody>")
        for row in rows:
            body.append(
                "<tr><td>{age}</td><td>{lives}</td><td>{ix}</td><td>{years}</td><td>{healthy}</td></tr>".format(
                    age=_esc(row.get("age")),
                    lives=_esc(row.get("lives")),
                    ix=_esc(row.get("disability_incidence_per_life")),
                    years=_esc(row.get("adl3_average_years")),
                    healthy=_esc(row.get("healthy_curtate_years")),
                )
            )
        body.append("</tbody></table>")
    decades = facts.get("decades") or []
    if decades:
        body.append("<h2>{}</h2>".format("עשורים" if he else "Decades"))
        body.append("<table><thead><tr><th>{}</th><th>{}</th></tr></thead><tbody>".format(
            "רצועה" if he else "Band", "חיים" if he else "Lives",
        ))
        for row in decades:
            body.append("<tr><td>{}–{}</td><td>{}</td></tr>".format(
                _esc(row.get("age_min")), _esc(row.get("age_max")), _esc(row.get("lives")),
            ))
        body.append("</tbody></table>")
    desks = [row for row in (report.get("dashboards") or []) if row.get("admin_open")]
    if desks:
        body.append("<h2>{}</h2><p>".format("לוחות" if he else "Dashboards"))
        body.append(" ".join(
            "<a href=\"{}\">{}</a>".format(_esc(row.get("path")), _esc(row.get("label_he") if he else row.get("label_en")))
            for row in desks
        ))
        body.append("</p>")
    integrity = report.get("integrity") or {}
    if he:
        footer = "חותם {seal} · {formula} · קריאה בלבד".format(
            seal=_esc(integrity.get("facts_sha256") or ""),
            formula=_esc(integrity.get("formula_id") or ""),
        )
        eyebrow = "ניהול AI ו-BI"
    else:
        footer = "Seal {seal} · {formula} · read only".format(
            seal=_esc(integrity.get("facts_sha256") or ""),
            formula=_esc(integrity.get("formula_id") or ""),
        )
        eyebrow = "Admin AI & BI"
    document = render_phins_document(
        title="PHINS admin report",
        eyebrow=eyebrow,
        subtitle=str(report.get("report_id") or ""),
        body_html="\n".join(part for part in body if part),
        footer=footer,
    )
    if he:
        document = document.replace('<html lang="en">', '<html lang="he" dir="rtl">', 1)
        document = document.replace(
            "</head>",
            "<style>html[dir=rtl] .phins-doc th,html[dir=rtl] .phins-doc td{text-align:right}"
            "html[dir=rtl] .phins-doc-kicker{text-align:left}</style></head>",
            1,
        )
    return document
