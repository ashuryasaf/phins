"""
PHINS BI and Statistical Analytics Service
==========================================
Comprehensive Business Intelligence and Statistical Analysis for:
- System optimization
- Performance metrics
- Predictive analytics
- Trend analysis
- KPI monitoring
- Community/Foundation analytics

Provides AI-driven insights for decision making across the platform.

Public API (consumed by `web_portal/api_bi_analytics.py`):
- BIAnalyticsService.get_executive_dashboard(customers, policies, claims, billing, balance_sheet, suppliers=None, deliveries=None)
- BIAnalyticsService.get_delivery_analytics(...)
- BIAnalyticsService.get_customer_analytics(...)
- BIAnalyticsService.get_supplier_analytics(...)
- BIAnalyticsService.generate_ai_insights(dashboard_data)
- BIAnalyticsService.predict_revenue_forecast(policies, historical_growth_rate=0.05, months_ahead=12)
- get_bi_analytics_service() — module-level singleton accessor
"""

import hashlib
import json
import math
import os
import statistics
import threading
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
import logging

from services import kpi_definitions as kpi
from services.agent_metrics import instrument_agent

logger = logging.getLogger('phins.bi_analytics')

# Minimum lives per smoking cohort before the slice publishes a loss-ratio
# comparison. Below this the cohort is reported with ``insufficient_data`` and
# no implied pricing factor is derived (claim counts are too volatile).
SMOKING_SLICE_MIN_LIVES = 30
# Claims are matched to the annual premium base with a trailing window, so the
# ratio is a period loss ratio rather than all-time claims over today's premium.
SMOKING_SLICE_WINDOW_MONTHS = 12
SMOKING_COHORTS = ('smoker', 'former', 'nonsmoker', 'unknown')
_INCURRED_CLAIM_STATUSES = ('approved', 'paid', 'closed')
_CLAIM_DATE_KEYS = ('incident_date', 'date_of_incident', 'loss_date', 'event_date',
                    'reported_date', 'filed_date', 'submitted_at', 'created_at')

# Revenue forecast defaults. The growth default is the legacy 5 %/month
# assumption; it is only used when the caller passes no rate AND the book has
# fewer than FORECAST_MIN_HISTORY_MONTHS complete months of policy history.
FORECAST_DEFAULT_MONTHLY_GROWTH = 0.05
FORECAST_DEFAULT_MONTHLY_GROWTH_SD = 0.04  # matches the Monte Carlo world default
FORECAST_MIN_HISTORY_MONTHS = 6
FORECAST_MAX_GROWTH_WINDOW_MONTHS = 12
_POLICY_START_KEYS = ('start_date', 'effective_date', 'approval_date', 'created_at')

# Mixed into every input fingerprint (B10). Bump when a dashboard's shape or
# arithmetic changes so a materialized view written by older code is never
# served by newer code even if the inputs are identical.
VIEW_SCHEMA_VERSION = 1
MATERIALIZED_VIEWS_FILENAME = 'materialized_views.json'


def _resolve_materialized_path() -> str:
    """``PHINS_BI_SNAPSHOT_DIR/materialized_views.json`` (same dir as BI-3 snapshots)."""
    configured = os.environ.get('PHINS_BI_SNAPSHOT_DIR', '').strip()
    if configured:
        base = configured
    else:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        base = os.path.join(root, 'data', 'bi_snapshots')
    return os.path.join(base, MATERIALIZED_VIEWS_FILENAME)


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)


def _record_sha256(record: Dict[str, Any]) -> str:
    return hashlib.sha256(
        _canonical_json({k: v for k, v in record.items() if k != 'record_sha256'}).encode('utf-8')
    ).hexdigest()


def _value_sha256(value: Any) -> str:
    """Digest of a dashboard payload minus its own timestamp fields."""
    if isinstance(value, dict):
        value = {k: v for k, v in value.items() if k not in ('computed_at', 'generated_at')}
    return hashlib.sha256(_canonical_json(value).encode('utf-8')).hexdigest()


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_month(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace('Z', '+00:00')
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            try:
                dt = datetime.strptime(text[:10], '%Y-%m-%d')
            except ValueError:
                return None
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None)


def _add_months(dt: datetime, n: int) -> datetime:
    month_index = dt.month - 1 + n
    return dt.replace(year=dt.year + month_index // 12, month=month_index % 12 + 1)


def _months_between(a: datetime, b: datetime) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def observed_monthly_growth(policies: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """Observed monthly MRR growth from policy start dates (read-only).

    Builds the *monthly* gross-adds MRR series by start month (every policy
    that was ever issued, so cancellations do not distort the *growth*
    estimate; churn is applied separately from the lapse table) up to the
    last complete month, then compares the mean monthly adds of the two
    halves of a window of at most ``FORECAST_MAX_GROWTH_WINDOW_MONTHS``
    months. Growth is measured on that new-business run-rate rather than on
    the accumulated book, because a stock that started from nothing grows
    with the book's age (level sales for six months would read as ~40 %/month)
    while the run-rate reads the sales trend the forecast compounds. Requires
    ``FORECAST_MIN_HISTORY_MONTHS`` complete months from the first start
    month; otherwise ``sufficient`` is False and no rate is returned.
    """
    now = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    current_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    adds: Dict[datetime, float] = defaultdict(float)
    for policy in (policies or {}).values():
        if not isinstance(policy, dict):
            continue
        start = next((_parse_month(policy.get(k)) for k in _POLICY_START_KEYS if policy.get(k)), None)
        if start is None or start >= current_month:
            continue  # no date, or in the current (incomplete) month / future
        adds[start] += kpi._num(policy.get('monthly_premium'))
    if not adds:
        return {'sufficient': False, 'history_months': 0, 'monthly_growth': None,
                'reason': 'no policies with a start date before the current month'}

    first = min(adds)
    last_complete = _add_months(current_month, -1)
    history_months = _months_between(first, last_complete) + 1
    series: List[float] = []
    month = first
    while month <= last_complete:
        series.append(adds.get(month, 0.0))
        month = _add_months(month, 1)

    result: Dict[str, Any] = {
        'history_months': history_months,
        'first_start_month': first.strftime('%Y-%m'),
        'last_complete_month': last_complete.strftime('%Y-%m'),
        'mrr_gross_adds_last_complete_month': round(series[-1], 2),
    }
    if history_months < FORECAST_MIN_HISTORY_MONTHS:
        result.update({'sufficient': False, 'monthly_growth': None,
                       'reason': f'need {FORECAST_MIN_HISTORY_MONTHS} complete months of policy history'})
        return result

    # Two equal halves of the window: the mean of each half averages out
    # month-to-month noise, and their ratio is the growth over ``half`` months.
    half = min(FORECAST_MAX_GROWTH_WINDOW_MONTHS // 2, len(series) // 2)
    earlier = sum(series[-2 * half:-half]) / half
    recent = sum(series[-half:]) / half
    if earlier <= 0 or recent <= 0:
        result.update({'sufficient': False, 'monthly_growth': None,
                       'reason': 'no new business in one half of the growth window'})
        return result
    growth = (recent / earlier) ** (1.0 / half) - 1.0
    step_growth = [series[i] / series[i - 1] - 1.0 for i in range(len(series) - 2 * half + 1, len(series))
                   if series[i - 1] > 0]
    sd = statistics.pstdev(step_growth) if len(step_growth) >= 2 else None
    result.update({
        'sufficient': True,
        'monthly_growth': round(growth, 6),
        'monthly_growth_sd': round(sd, 6) if sd is not None else None,
        'window_months': 2 * half,
        'basis': 'geometric growth between the mean monthly gross-adds MRR of the two halves of the window',
    })
    return result


def _lapse_rate_year1_from_store() -> tuple:
    """Year-1 lapse rate from the actuarial store, with a labelled fallback."""
    try:
        from services.actuarial_service import get_actuarial_store
        store = get_actuarial_store()
        return float(store.get_lapse_rate(1)), f'actuarial_lapse_table:{getattr(store, "current_version", "")}'
    except Exception:
        return 0.08, 'default_lapse_year1'


def _normalize_smoking(raw: Any) -> str:
    """Map free-text smoking status onto the pricing kernel's cohorts.

    Reuses the kernel's normaliser so this slice groups lives exactly the way
    pricing does; anything the kernel cannot classify is ``unknown``.
    """
    try:
        from services.pricing_kernel import _normalize_smoking_status
        return _normalize_smoking_status(raw) or 'unknown'
    except Exception:
        return 'unknown'


def _resolve_smoking_status(policy: Dict[str, Any], customer: Optional[Dict[str, Any]],
                            latest_application: Optional[Dict[str, Any]]) -> str:
    for source in (policy, customer or {}, latest_application or {}):
        for key in ('smoking_status', 'smoker', 'tobacco', 'smoking'):
            value = source.get(key)
            if value is not None and value != '':
                return _normalize_smoking(value)
    return 'unknown'


def _latest_applications_by_customer(applications: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    for app in (applications or {}).values():
        if not isinstance(app, dict):
            continue
        cid = app.get('customer_id')
        if not cid:
            continue
        stamp = str(app.get('submitted_at') or app.get('created_at') or '')
        if cid not in latest or stamp >= str(latest[cid].get('submitted_at') or latest[cid].get('created_at') or ''):
            latest[cid] = app
    return latest


def loss_ratio_by_smoking_status(
    customers: Dict[str, Any],
    policies: Dict[str, Any],
    claims: Dict[str, Any],
    underwriting_applications: Optional[Dict[str, Any]] = None,
    pricing_factors: Optional[Dict[str, Any]] = None,
    min_lives: int = SMOKING_SLICE_MIN_LIVES,
    window_months: int = SMOKING_SLICE_WINDOW_MONTHS,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Observed loss ratio by smoking cohort from real policies and claims.

    Read-only. Premium base is the annual premium of active policies (the
    same base as the BI ``loss_ratio`` KPI); claims are attributed to the
    cohort of their policy (falling back to the claimant's customer record).
    ``claims_incurred`` counts approved/paid/closed claims at approved amount;
    ``claims_paid`` counts paid claims only (the KPI basis).

    Numerator and denominator cover the same exposure: a claim only counts
    when it belongs to the active book that supplies the premium, and only
    when it falls inside the trailing ``window_months`` (0 disables the
    window). Claims on lapsed policies and older claims are excluded and
    counted separately, so cohorts with different tenure or lapse experience
    are not compared on mismatched bases.

    When both the smoker and nonsmoker cohorts reach ``min_lives`` the slice
    reports the smoker/nonsmoker loss-ratio ratio and, if ``pricing_factors``
    (the live ``smoker_mortality_factor`` / ``smoker_disability_factor``) are
    supplied, the factor that ratio implies: premium already scales with the
    live factor, so a residual loss-ratio ratio ``r`` implies ``factor × r``.
    Nothing is written; the response says where the factor is adjusted.
    """
    latest_apps = _latest_applications_by_customer(underwriting_applications)
    cohorts: Dict[str, Dict[str, Any]] = {
        key: {'cohort': key, 'lives': 0, 'annual_premium': 0.0, 'claims_count': 0,
              'claims_incurred': 0.0, 'claims_paid': 0.0}
        for key in SMOKING_COHORTS
    }
    # Both maps cover the active premium base only; ``inactive_policy_ids``
    # keeps the claims loop from charging a lapsed policy's claim to it.
    policy_cohort: Dict[str, str] = {}
    customer_cohort: Dict[str, str] = {}
    inactive_policy_ids: set = set()

    for pid, policy in (policies or {}).items():
        if not isinstance(policy, dict):
            continue
        cid = policy.get('customer_id')
        customer = (customers or {}).get(cid) if cid else None
        cohort = _resolve_smoking_status(policy, customer if isinstance(customer, dict) else None,
                                         latest_apps.get(cid) if cid else None)
        keys = {str(policy.get('id') or policy.get('policy_id') or pid), str(pid)}
        if str(policy.get('status', '')).lower() != 'active':
            inactive_policy_ids.update(keys)
            continue
        for key in keys:
            policy_cohort[key] = cohort
        if cid and cid not in customer_cohort:
            customer_cohort[str(cid)] = cohort
        row = cohorts[cohort]
        row['lives'] += 1
        row['annual_premium'] += kpi._num(policy.get('annual_premium'))

    cutoff = None
    if int(window_months) > 0:
        current_month = (now or datetime.now(timezone.utc)).replace(
            tzinfo=None, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        cutoff = _add_months(current_month, -(int(window_months) - 1))

    unattributed = 0
    off_exposure = 0
    outside_window = 0
    undated = 0
    for claim in (claims or {}).values():
        if not isinstance(claim, dict):
            continue
        status = str(claim.get('status', '')).lower()
        if status not in _INCURRED_CLAIM_STATUSES:
            continue
        claim_month = next((_parse_month(claim.get(k)) for k in _CLAIM_DATE_KEYS if claim.get(k)), None)
        if claim_month is not None and cutoff is not None and claim_month < cutoff:
            outside_window += 1
            continue
        policy_key = str(claim.get('policy_id') or '')
        cohort = policy_cohort.get(policy_key)
        if cohort is None and policy_key in inactive_policy_ids:
            off_exposure += 1  # policy carries no premium in the base
            continue
        if claim_month is None:
            undated += 1  # undated claims stay in; the count says how many
        if cohort is None:
            cohort = customer_cohort.get(str(claim.get('customer_id') or ''))
        if cohort is None:
            cohort = 'unknown'
            unattributed += 1
        amount = kpi._num(claim.get('approved_amount', claim.get('claimed_amount')))
        row = cohorts[cohort]
        row['claims_count'] += 1
        row['claims_incurred'] += amount
        if status == 'paid':
            row['claims_paid'] += amount

    rows: List[Dict[str, Any]] = []
    for key in SMOKING_COHORTS:
        row = cohorts[key]
        premium = row['annual_premium']
        row['annual_premium'] = round(premium, 2)
        row['claims_incurred'] = round(row['claims_incurred'], 2)
        row['claims_paid'] = round(row['claims_paid'], 2)
        row['loss_ratio_pct'] = round(kpi.loss_ratio_pct(row['claims_paid'], premium), 2)
        row['incurred_loss_ratio_pct'] = round(kpi.loss_ratio_pct(row['claims_incurred'], premium), 2)
        row['insufficient_data'] = row['lives'] < int(min_lives)
        rows.append(row)
    by_cohort = {row['cohort']: row for row in rows}

    smoker, nonsmoker = by_cohort['smoker'], by_cohort['nonsmoker']
    sufficient = (not smoker['insufficient_data'] and not nonsmoker['insufficient_data']
                  and nonsmoker['incurred_loss_ratio_pct'] > 0)
    comparison: Dict[str, Any] = {
        'sufficient': sufficient,
        'min_lives_per_cohort': int(min_lives),
        'smoker_lives': smoker['lives'],
        'nonsmoker_lives': nonsmoker['lives'],
        'basis': ('incurred (approved/paid/closed) claims on the active book, within the trailing '
                  'window, ÷ annual premium of active policies'),
    }
    if sufficient:
        ratio = smoker['incurred_loss_ratio_pct'] / nonsmoker['incurred_loss_ratio_pct']
        comparison['smoker_to_nonsmoker_loss_ratio_ratio'] = round(ratio, 4)
        comparison['gap_pts'] = round(smoker['incurred_loss_ratio_pct'] - nonsmoker['incurred_loss_ratio_pct'], 2)
        if pricing_factors:
            implied = {}
            for key in ('smoker_mortality_factor', 'smoker_disability_factor'):
                live = pricing_factors.get(key)
                if live is not None:
                    implied[key] = round(max(1.0, min(3.0, kpi._num(live, 1.0) * ratio)), 4)
            comparison['live_factors'] = {k: pricing_factors.get(k) for k in ('smoker_mortality_factor', 'smoker_disability_factor')}
            comparison['implied_factors'] = implied
            comparison['implied_factor_basis'] = 'live factor × observed smoker/nonsmoker loss-ratio ratio, clamped 1.0–3.0'
    else:
        comparison['reason'] = (
            'nonsmoker cohort has no incurred claims' if not nonsmoker['insufficient_data'] and not smoker['insufficient_data']
            else f'need at least {int(min_lives)} active lives in both the smoker and nonsmoker cohorts'
        )

    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'read_only': True,
        'source': 'observed_policies_and_claims',
        'loss_ratio_basis': kpi.LOSS_RATIO_BASES['paid_claims'],
        'cohorts': rows,
        'experience_window_months': int(window_months),
        'claims_unattributed_to_policy_or_customer': unattributed,
        'claims_excluded_off_active_exposure': off_exposure,
        'claims_excluded_outside_window': outside_window,
        'claims_without_a_date_included': undated,
        'comparison': comparison,
        'adjust_via': 'POST /api/actuarial/config {"smoker_mortality_factor": <f>, "smoker_disability_factor": <f>, "change_reason": "..."}',
    }


# ---------------------------------------------------------------------------
# Enums and dataclasses
#
# Preserved for backward compatibility — external modules and tests import
# `MetricCategory` and related symbols from this module.
# ---------------------------------------------------------------------------


class MetricCategory(Enum):
    """Categories of metrics."""
    FINANCIAL = "financial"
    OPERATIONAL = "operational"
    CUSTOMER = "customer"
    SUPPLIER = "supplier"
    CLAIMS = "claims"
    UNDERWRITING = "underwriting"
    MARKETPLACE = "marketplace"
    FOUNDATION = "foundation"
    DELIVERY = "delivery"


class TrendDirection(Enum):
    """Trend direction indicators."""
    STRONG_UP = "strong_up"
    UP = "up"
    STABLE = "stable"
    DOWN = "down"
    STRONG_DOWN = "strong_down"


class AlertSeverity(Enum):
    """Alert severity levels."""
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class KPIMetric:
    """Key Performance Indicator metric."""
    name: str
    category: MetricCategory
    value: float
    unit: str
    period: str
    trend: TrendDirection = TrendDirection.STABLE
    change_percentage: float = 0.0
    target: Optional[float] = None
    target_achieved: bool = True
    historical_values: List[float] = field(default_factory=list)

    def to_dict(self) -> Dict:
        result = asdict(self)
        result['category'] = self.category.value
        result['trend'] = self.trend.value
        return result


@dataclass
class BIInsight:
    """Business Intelligence insight."""
    insight_id: str
    category: str
    title: str
    description: str
    severity: AlertSeverity
    metric_value: Optional[float] = None
    recommendation: Optional[str] = None
    affected_entities: List[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict:
        result = asdict(self)
        result['severity'] = self.severity.value
        return result


@dataclass
class StatisticalSummary:
    """Statistical summary of a data series."""
    count: int
    mean: float
    median: float
    std_dev: float
    min_value: float
    max_value: float
    percentile_25: float
    percentile_75: float
    variance: float

    def to_dict(self) -> Dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------


class BIAnalyticsService:
    """
    Business Intelligence and Analytics Service for PHINS platform.

    All dashboard methods accept their data sources as keyword arguments rather
    than holding references — this keeps the singleton compatible with the
    runtime storage-swap performed by `attempt_database_recovery` in
    `web_portal/server.py`. (See `PHINS_PLATFORM_ASSESSMENT.md` §2.1.)
    """

    def __init__(self, cache_ttl_seconds: int = 300, materialized_path: Optional[str] = None):
        # BI-2: the cache is now wired into every dashboard method. Each entry is
        # keyed by method name + a cheap content fingerprint of the inputs, so a
        # cached dashboard can never contradict a changed data store (when the
        # underlying data changes, the fingerprint changes and we recompute).
        # The cache holds READ-ONLY derived views; it is never a write source.
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache_lock = threading.Lock()
        # B10: write-path invalidation. ``data_version`` climbs on every
        # notified store write (DatabaseDict listener, ledger save, explicit
        # hooks). It is diagnostic and drives re-materialization; it never
        # *replaces* the fingerprint check below, so an un-hooked write can
        # at worst cost a recompute, never serve a contradicting dashboard.
        self.data_version = 0
        self.last_data_change_at: Optional[str] = None
        self._changed_stores: Dict[str, int] = defaultdict(int)
        self._on_change: List[Callable[[str], None]] = []
        # Per-store digest memo for versioned stores (``content_version()``):
        # id(store) -> (version, digest). Lets the fingerprint be O(1) when a
        # DatabaseDict reports no change instead of re-hashing every row.
        self._source_digests: Dict[int, tuple] = {}
        self._local = threading.local()
        # B10: materialized views persisted under PHINS_BI_SNAPSHOT_DIR so a
        # scheduler (or another process) can compute dashboards off the
        # request path and a fresh, fingerprint-matching copy is served here.
        self._materialized_path = materialized_path or _resolve_materialized_path()
        self._materialized_lock = threading.RLock()
        self._materialized_mtime: Optional[float] = None
        self._materialized_records: Dict[str, Dict[str, Any]] = {}
        self._load_materialized(force=True)
        logger.info("BI Analytics Service initialized")

    # ------------------------------------------------------------------
    # Caching primitives (BI-2) + write-path invalidation (B10)
    # ------------------------------------------------------------------

    @staticmethod
    def _digest_store(src: Any) -> str:
        """Content digest of one dict-like store (rows hashed in key order)."""
        hasher = hashlib.sha256()
        hasher.update(str(len(src)).encode())
        # Sort keys so ordering never affects the fingerprint.
        for key in sorted(src.keys(), key=str):
            val = src[key]
            hasher.update(repr(key).encode())
            try:
                hasher.update(json.dumps(val, sort_keys=True, default=str).encode())
            except (TypeError, ValueError):
                hasher.update(repr(val).encode())
        return hasher.hexdigest()

    def _source_digest(self, src: Any) -> str:
        """Digest of one input, memoised for stores that publish a version.

        A store exposing ``content_version()`` (``DatabaseDict``) bumps it on
        every local write and on every refresh that loaded different rows, so
        an unchanged version proves the rows are unchanged and the previous
        digest is exact. Plain dicts (in-memory mode) are always re-hashed:
        nothing tracks in-place edits there, and correctness comes first.
        """
        version_fn = getattr(src, 'content_version', None)
        if callable(version_fn) and hasattr(src, 'keys'):
            version = version_fn()  # freshness-checked: may refresh from the DB
            memo = self._source_digests.get(id(src))
            if memo is not None and memo[0] == version and memo[2] is src:
                return memo[1]
            # Snapshot the rows once (bulk read, no per-key queries) so the
            # digest and the version agree.
            rows = src if isinstance(src, dict) else dict(src.items())
            digest = self._digest_store(rows)
            self._source_digests[id(src)] = (version, digest, src)
            return digest
        if isinstance(src, dict) or hasattr(src, 'keys'):
            return self._digest_store(src)
        try:
            return hashlib.sha256(json.dumps(src, sort_keys=True, default=str).encode()).hexdigest()
        except (TypeError, ValueError):
            return hashlib.sha256(repr(src).encode()).hexdigest()

    def _fingerprint(self, *sources: Any) -> str:
        """Cheap, stable content fingerprint over dashboard inputs.

        Single pass over the inputs; far cheaper than the multi-aggregation
        dashboards it guards, but sensitive enough that *any* field change
        invalidates the cache. We hash the full content of each record (not a
        hand-picked subset) so a cached dashboard can never contradict changed
        inputs — every KPI driver, including fields like ``bid_amount``,
        ``distance_km``, ``urgency``, ``customer_id`` and ``category``, is
        covered. ``VIEW_SCHEMA_VERSION`` is mixed in so a materialized view
        written by older dashboard code is never adopted by newer code.
        """
        hasher = hashlib.sha256()
        hasher.update(f'schema:{VIEW_SCHEMA_VERSION}'.encode())
        for src in sources:
            # ``None`` and ``{}`` are the same input to every dashboard
            # (optional stores default to empty), so they must fingerprint alike.
            hasher.update(self._source_digest({} if src is None else src).encode())
        return hasher.hexdigest()

    def _cached(self, key: str, fingerprint: str, compute: Callable[[], Any]) -> Any:
        """Return a cached value if fresh and inputs unchanged, else recompute.

        On *any* doubt (TTL elapsed or fingerprint mismatch) we recompute, so the
        cache can only ever return data consistent with the current inputs.
        A materialized copy written by a scheduler for the same fingerprint
        counts as fresh when it is younger than the TTL. Every value carries
        ``computed_at`` (UTC ISO) so a consumer can see how old it is.
        """
        now = time.monotonic()
        with self._cache_lock:
            entry = self.cache.get(key)
            if (
                entry is not None
                and entry.get('fingerprint') == fingerprint
                and (now - entry.get('stored_at', 0)) < self.cache_ttl_seconds
            ):
                entry['hits'] = entry.get('hits', 0) + 1
                self._local.served_from = 'cache'
                return entry['value']

        materialized = self._materialized_entry(key, fingerprint)
        if materialized is not None:
            with self._cache_lock:
                self.cache[key] = materialized
            self._local.served_from = 'materialized'
            return materialized['value']

        value = compute()
        computed_at = datetime.now(timezone.utc).isoformat()
        if isinstance(value, dict):
            value['computed_at'] = computed_at
        with self._cache_lock:
            self.cache[key] = {
                'fingerprint': fingerprint,
                'stored_at': now,
                'computed_at': computed_at,
                'data_version': self.data_version,
                'hits': 0,
                'value': value,
            }
        self._local.served_from = 'live'
        return value

    def last_served_from(self) -> Optional[str]:
        """How the most recent dashboard call on this thread was answered:
        ``'cache'``, ``'materialized'`` or ``'live'``."""
        return getattr(self._local, 'served_from', None)

    def cache_entry(self, key: str) -> Optional[Dict[str, Any]]:
        """Metadata (no value) for one cached view, or None."""
        with self._cache_lock:
            entry = self.cache.get(key)
            if entry is None:
                return None
            return {
                'computed_at': entry.get('computed_at'),
                'age_seconds': round(time.monotonic() - entry.get('stored_at', 0), 3),
                'data_version': entry.get('data_version'),
                'hits': entry.get('hits', 0),
                'fingerprint': entry.get('fingerprint'),
            }

    def invalidate_cache(self) -> None:
        """Drop all cached dashboards (e.g. after a bulk data import)."""
        with self._cache_lock:
            self.cache.clear()
            self._source_digests.clear()

    def notify_data_change(self, store: str = '*') -> int:
        """Write-path hook: a BI input store was (or may have been) written.

        Bumps ``data_version`` and runs the registered ``on_data_change``
        callbacks (the portal uses one to re-materialize dashboards off the
        request path). Cached views are *not* dropped here: the fingerprint
        decides on the next read whether the write actually changed a BI
        input, so a burst of writes costs at most one recompute per view.
        """
        with self._cache_lock:
            self.data_version += 1
            self._changed_stores[str(store or '*')] += 1
            self.last_data_change_at = datetime.now(timezone.utc).isoformat()
            version = self.data_version
            callbacks = list(self._on_change)
        for callback in callbacks:
            try:
                callback(str(store or '*'))
            except Exception as exc:  # a re-materialization hook must never break a write
                logger.warning("BI data-change callback failed: %s", exc)
        return version

    def on_data_change(self, callback: Callable[[str], None]) -> None:
        """Register ``callback(store)`` to run after each notified write."""
        with self._cache_lock:
            if callback not in self._on_change:
                self._on_change.append(callback)

    def remove_data_change_callback(self, callback: Callable[[str], None]) -> None:
        with self._cache_lock:
            if callback in self._on_change:
                self._on_change.remove(callback)

    # ------------------------------------------------------------------
    # Materialized views (B10)
    # ------------------------------------------------------------------

    def _load_materialized(self, force: bool = False) -> None:
        """(Re)load the materialized-view file when its mtime changed."""
        path = self._materialized_path
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            with self._materialized_lock:
                self._materialized_records = {}
                self._materialized_mtime = None
            return
        if not force and mtime == self._materialized_mtime:
            return
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                payload = json.load(fh)
            views = payload.get('views') if isinstance(payload, dict) else None
            records: Dict[str, Dict[str, Any]] = {}
            for name, record in (views or {}).items():
                if not isinstance(record, dict) or not isinstance(record.get('value'), dict):
                    continue
                if _record_sha256(record) != record.get('record_sha256'):
                    logger.error("Materialized BI view %s failed its checksum in %s; ignored.", name, path)
                    continue
                records[str(name)] = record
            with self._materialized_lock:
                self._materialized_records = records
                self._materialized_mtime = mtime
        except Exception as exc:
            logger.warning("Materialized BI views unreadable (%s): %s", path, exc)

    def _materialized_entry(self, key: str, fingerprint: str) -> Optional[Dict[str, Any]]:
        """A cache entry built from a fresh, fingerprint-matching materialized view."""
        self._load_materialized()
        with self._materialized_lock:
            record = self._materialized_records.get(key)
        if record is None or record.get('fingerprint') != fingerprint:
            return None
        computed_at = _parse_iso(record.get('computed_at'))
        if computed_at is None:
            return None
        age = (datetime.now(timezone.utc) - computed_at).total_seconds()
        if age < 0 or age >= self.cache_ttl_seconds:
            return None
        value = json.loads(json.dumps(record['value']))  # private copy
        value['computed_at'] = record.get('computed_at')
        return {
            'fingerprint': fingerprint,
            'stored_at': time.monotonic() - age,
            'computed_at': record.get('computed_at'),
            'data_version': record.get('data_version'),
            'hits': 1,
            'value': value,
        }

    def materialize_views(self, data_sources: Dict[str, Any], *, source: str = 'scheduler') -> Dict[str, Any]:
        """Compute the standard dashboards and persist them as materialized views.

        Runs the same getters a request would (so this process's cache is
        warmed too) and upserts one record per view — ``executive_dashboard``,
        ``revenue_forecast`` (default parameters) and ``customer_analytics`` —
        into ``PHINS_BI_SNAPSHOT_DIR/materialized_views.json`` with the input
        fingerprint, ``computed_at`` and a checksum. Idempotent: a re-run with
        unchanged inputs rewrites the same view (fresh ``computed_at``); it
        never accumulates records or duplicates history (that is the BI-3
        snapshot log). Never raises: a persistence failure is reported.
        """
        ds = data_sources or {}
        computed: Dict[str, Dict[str, Any]] = {}
        errors: Dict[str, str] = {}

        def _run(name: str, fn: Callable[[], Any]) -> None:
            try:
                value = fn()
                entry = self.cache_entry(name)
                if isinstance(value, dict) and entry is not None:
                    computed[name] = {'value': value, 'fingerprint': entry['fingerprint'],
                                      'computed_at': value.get('computed_at') or entry['computed_at']}
            except Exception as exc:
                errors[name] = str(exc)

        _run('executive_dashboard', lambda: self.get_executive_dashboard(
            customers=ds.get('customers', {}) or {}, policies=ds.get('policies', {}) or {},
            claims=ds.get('claims', {}) or {}, billing=ds.get('billing', {}) or {},
            balance_sheet=ds.get('balance_sheet', {}) or {}, suppliers=ds.get('suppliers', {}) or {},
            deliveries=ds.get('deliveries', {}) or {}))
        _run('revenue_forecast', lambda: self.predict_revenue_forecast(
            policies=ds.get('policies', {}) or {}, historical_growth_rate=None))
        _run('customer_analytics', lambda: self.get_customer_analytics(
            customers=ds.get('customers', {}) or {}, health_wallets=ds.get('health_wallets', {}) or {},
            investment_accounts=ds.get('investment_accounts', {}) or {},
            transaction_ledger=ds.get('transaction_ledger', {}) or {},
            policies=ds.get('policies', {}) or {}))

        now_iso = datetime.now(timezone.utc).isoformat()
        self._load_materialized()
        with self._materialized_lock:
            records = dict(self._materialized_records)
            changed: Dict[str, bool] = {}
            for name, item in computed.items():
                previous = records.get(name)
                record = {
                    'view': name,
                    'fingerprint': item['fingerprint'],
                    'computed_at': item['computed_at'],
                    'data_version': self.data_version,
                    'source': source,
                    'schema_version': VIEW_SCHEMA_VERSION,
                    'value': item['value'],
                }
                record['record_sha256'] = _record_sha256(record)
                changed[name] = (previous is None
                                 or previous.get('fingerprint') != record['fingerprint']
                                 or _value_sha256(previous.get('value')) != _value_sha256(record['value']))
                records[name] = record
            persisted, error = self._write_materialized(records, now_iso)
            if persisted:
                self._materialized_records = records
                try:
                    self._materialized_mtime = os.path.getmtime(self._materialized_path)
                except OSError:
                    pass
        result = {
            'success': not errors and persisted,
            'written_at': now_iso,
            'path': self._materialized_path,
            'persisted': persisted,
            'data_version': self.data_version,
            'views': {name: {'computed_at': item['computed_at'], 'fingerprint': item['fingerprint'],
                             'changed': changed.get(name, False)} for name, item in computed.items()},
        }
        if errors:
            result['errors'] = errors
        if error:
            result['error'] = error
        return result

    def _write_materialized(self, records: Dict[str, Dict[str, Any]], written_at: str) -> tuple:
        """Atomic replace of the materialized-view file. Returns (ok, error)."""
        path = self._materialized_path
        tmp_path = f'{path}.tmp-{os.getpid()}'
        try:
            os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
            payload = {'schema': VIEW_SCHEMA_VERSION, 'written_at': written_at, 'views': records}
            with open(tmp_path, 'w', encoding='utf-8') as fh:
                json.dump(payload, fh, ensure_ascii=False, default=str)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, path)
            return True, None
        except Exception as exc:
            logger.warning("Materialized BI views not persisted (%s): %s", path, exc)
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return False, str(exc)

    def materialized_views(self) -> Dict[str, Dict[str, Any]]:
        """Metadata (no values) of the persisted materialized views."""
        self._load_materialized()
        with self._materialized_lock:
            return {
                name: {k: record.get(k) for k in ('computed_at', 'fingerprint', 'data_version', 'source')}
                for name, record in self._materialized_records.items()
            }

    def describe(self) -> Dict[str, Any]:
        """Diagnostics for the agent health probe (no dashboard values)."""
        with self._cache_lock:
            keys = list(self.cache.keys())
            changed = dict(self._changed_stores)
        return {
            'cache_ttl_seconds': self.cache_ttl_seconds,
            'data_version': self.data_version,
            'last_data_change_at': self.last_data_change_at,
            'changed_stores': changed,
            'cached_views': {key: self.cache_entry(key) for key in keys},
            'materialized_path': self._materialized_path,
            'materialized_views': self.materialized_views(),
        }

    # ------------------------------------------------------------------
    # Executive dashboard
    # ------------------------------------------------------------------

    @instrument_agent('bi_analytics')
    def get_executive_dashboard(
        self,
        customers: Dict[str, Any],
        policies: Dict[str, Any],
        claims: Dict[str, Any],
        billing: Dict[str, Any],
        balance_sheet: Dict[str, Any],
        suppliers: Optional[Dict[str, Any]] = None,
        deliveries: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate executive dashboard with high-level KPIs (cached, BI-2)."""
        fingerprint = self._fingerprint(
            customers, policies, claims, billing, balance_sheet, suppliers, deliveries
        )
        return self._cached(
            'executive_dashboard',
            fingerprint,
            lambda: self._compute_executive_dashboard(
                customers, policies, claims, billing, balance_sheet,
                suppliers, deliveries,
            ),
        )

    def _compute_executive_dashboard(
        self,
        customers: Dict[str, Any],
        policies: Dict[str, Any],
        claims: Dict[str, Any],
        billing: Dict[str, Any],
        balance_sheet: Dict[str, Any],
        suppliers: Optional[Dict[str, Any]] = None,
        deliveries: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)

        total_customers = len(customers)
        active_customers = sum(
            1 for c in customers.values() if c.get('status') == 'active'
        )

        total_policies = len(policies)
        active_policies = sum(
            1 for p in policies.values() if p.get('status') == 'active'
        )
        total_coverage = sum(p.get('coverage_amount', 0) for p in policies.values())

        monthly_premium_revenue = sum(
            p.get('monthly_premium', 0)
            for p in policies.values()
            if p.get('status') == 'active'
        )
        annual_premium_revenue = sum(
            p.get('annual_premium', 0)
            for p in policies.values()
            if p.get('status') == 'active'
        )

        total_claims = len(claims)
        claims_by_status: Dict[str, int] = defaultdict(int)
        total_claimed = 0.0
        total_approved = 0.0
        total_paid = 0.0
        for claim in claims.values():
            status = str(claim.get('status', '')).lower()
            claims_by_status[status] += 1
            total_claimed += claim.get('claimed_amount', 0)
            if status in ('approved', 'paid', 'closed'):
                total_approved += claim.get('approved_amount', 0)
            if status == 'paid':
                total_paid += claim.get('approved_amount', 0)

        claims_approval_rate = kpi.approval_rate_pct(total_approved, total_claimed)

        outstanding_amount = sum(
            b.get('amount', 0) - b.get('amount_paid', 0)
            for b in billing.values()
            if b.get('status') != 'paid'
        )

        total_assets = balance_sheet.get('total_assets', 0)
        claims_reserve = balance_sheet.get('claims_reserve', 0)
        total_liabilities = balance_sheet.get('total_liabilities', 0)
        net_worth = kpi.net_worth(total_assets, total_liabilities)

        supplier_metrics: Dict[str, Any] = {}
        if suppliers:
            supplier_metrics = {
                'total_suppliers': len(suppliers),
                'active_suppliers': sum(
                    1 for s in suppliers.values() if s.get('status') == 'approved'
                ),
                'pending_approval': sum(
                    1 for s in suppliers.values() if s.get('status') == 'pending'
                ),
            }

        delivery_metrics: Dict[str, Any] = {}
        if deliveries:
            delivery_metrics = {
                'active_deliveries': sum(
                    1 for d in deliveries.values()
                    if d.get('status') not in ('completed', 'cancelled')
                ),
                'completed_deliveries': sum(
                    1 for d in deliveries.values() if d.get('status') == 'completed'
                ),
                'total_deliveries': len(deliveries),
            }

        financial_health_score = self._calculate_financial_health_score(
            balance_sheet, monthly_premium_revenue, total_paid
        )
        operational_health_score = self._calculate_operational_health_score(
            claims_approval_rate, outstanding_amount, annual_premium_revenue
        )

        return {
            'generated_at': now.isoformat(),
            'summary': {
                'total_customers': total_customers,
                'active_customers': active_customers,
                'total_policies': total_policies,
                'active_policies': active_policies,
                'total_claims': total_claims,
                'monthly_revenue': monthly_premium_revenue,
                'annual_revenue_projection': annual_premium_revenue,
            },
            'financial': {
                'total_assets': total_assets,
                'total_liabilities': total_liabilities,
                'net_worth': net_worth,
                'claims_reserve': claims_reserve,
                'outstanding_receivables': outstanding_amount,
                'total_coverage': total_coverage,
                'loss_ratio': kpi.loss_ratio_pct(total_paid, annual_premium_revenue),
            },
            'claims': {
                'total': total_claims,
                'by_status': dict(claims_by_status),
                'total_claimed': total_claimed,
                'total_approved': total_approved,
                'total_paid': total_paid,
                'approval_rate': round(claims_approval_rate, 2),
            },
            'health_scores': {
                'financial_health': financial_health_score,
                'operational_health': operational_health_score,
                'overall_health': round(
                    (financial_health_score + operational_health_score) / 2, 2
                ),
            },
            'supplier_metrics': supplier_metrics,
            'delivery_metrics': delivery_metrics,
        }

    # ------------------------------------------------------------------
    # Delivery / customer / supplier analytics
    # ------------------------------------------------------------------

    def get_delivery_analytics(
        self,
        delivery_requests: Dict[str, Any],
        delivery_bids: Dict[str, Any],
        active_deliveries: Dict[str, Any],
        delivery_history: Dict[str, Any],
        supplier_metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Analyze delivery system performance (cached, BI-2)."""
        fingerprint = self._fingerprint(
            delivery_requests, delivery_bids, active_deliveries,
            delivery_history, supplier_metrics,
        )
        return self._cached(
            'delivery_analytics',
            fingerprint,
            lambda: self._compute_delivery_analytics(
                delivery_requests, delivery_bids, active_deliveries,
                delivery_history, supplier_metrics,
            ),
        )

    def _compute_delivery_analytics(
        self,
        delivery_requests: Dict[str, Any],
        delivery_bids: Dict[str, Any],
        active_deliveries: Dict[str, Any],
        delivery_history: Dict[str, Any],
        supplier_metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        total_requests = len(delivery_requests)
        open_requests = sum(
            1 for r in delivery_requests.values()
            if r.get('status') == 'open_for_bidding'
        )
        accepted_requests = sum(
            1 for r in delivery_requests.values()
            if r.get('status') == 'bid_accepted'
        )

        total_bids = len(delivery_bids)
        avg_bids_per_request = (
            total_bids / total_requests if total_requests > 0 else 0
        )

        bid_amounts = [b.get('bid_amount', 0) for b in delivery_bids.values()]
        avg_bid_amount = statistics.mean(bid_amounts) if bid_amounts else 0
        median_bid_amount = statistics.median(bid_amounts) if bid_amounts else 0

        total_active = len(active_deliveries)
        total_completed = len(delivery_history)

        on_time_deliveries = 0
        late_deliveries = 0
        for delivery in delivery_history.values():
            estimated = delivery.get('estimated_delivery_time')
            actual = delivery.get('actual_delivery_time')
            if not estimated or not actual:
                continue
            try:
                est_dt = datetime.fromisoformat(estimated)
                act_dt = datetime.fromisoformat(actual)
                if act_dt <= est_dt:
                    on_time_deliveries += 1
                else:
                    late_deliveries += 1
            except (TypeError, ValueError):
                continue

        timed_total = on_time_deliveries + late_deliveries
        on_time_rate = (
            (on_time_deliveries / timed_total * 100) if timed_total > 0 else 0
        )

        top_suppliers = sorted(
            supplier_metrics.items(),
            key=lambda x: x[1].get('total_deliveries', 0),
            reverse=True,
        )[:5]
        top_suppliers_data = [
            {
                'supplier_id': sup_id,
                'total_deliveries': metrics.get('total_deliveries', 0),
                'total_revenue': metrics.get('total_revenue', 0),
                'rating': metrics.get('rating', 0),
                'reliability_score': metrics.get('reliability_score', 0),
            }
            for sup_id, metrics in top_suppliers
        ]

        distances = [r.get('distance_km', 0) for r in delivery_requests.values()]
        avg_distance = statistics.mean(distances) if distances else 0

        urgency_breakdown: Dict[str, int] = defaultdict(int)
        for request in delivery_requests.values():
            urgency_breakdown[request.get('urgency', 'standard')] += 1

        return {
            'requests': {
                'total': total_requests,
                'open_for_bidding': open_requests,
                'bid_accepted': accepted_requests,
                'avg_distance_km': round(avg_distance, 2),
                'urgency_breakdown': dict(urgency_breakdown),
            },
            'bids': {
                'total': total_bids,
                'avg_per_request': round(avg_bids_per_request, 2),
                'avg_amount': round(avg_bid_amount, 2),
                'median_amount': round(median_bid_amount, 2),
            },
            'deliveries': {
                'active': total_active,
                'completed': total_completed,
                'total': total_active + total_completed,
                'on_time_deliveries': on_time_deliveries,
                'late_deliveries': late_deliveries,
                'on_time_rate': round(on_time_rate, 2),
            },
            'suppliers': {
                'total_active': len(supplier_metrics),
                'top_performers': top_suppliers_data,
            },
        }

    def get_customer_analytics(
        self,
        customers: Dict[str, Any],
        health_wallets: Dict[str, Any],
        investment_accounts: Dict[str, Any],
        transaction_ledger: Dict[str, Any],
        policies: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Analyze customer behavior and engagement (cached, BI-2)."""
        fingerprint = self._fingerprint(
            customers, health_wallets, investment_accounts,
            transaction_ledger, policies,
        )
        return self._cached(
            'customer_analytics',
            fingerprint,
            lambda: self._compute_customer_analytics(
                customers, health_wallets, investment_accounts,
                transaction_ledger, policies,
            ),
        )

    def _compute_customer_analytics(
        self,
        customers: Dict[str, Any],
        health_wallets: Dict[str, Any],
        investment_accounts: Dict[str, Any],
        transaction_ledger: Dict[str, Any],
        policies: Dict[str, Any],
    ) -> Dict[str, Any]:
        total_customers = len(customers)

        wallet_balances = [w.get('balance', 0) for w in health_wallets.values()]
        total_wallet_balance = sum(wallet_balances)
        avg_wallet_balance = (
            statistics.mean(wallet_balances) if wallet_balances else 0
        )

        customers_with_wallets = len(health_wallets)
        wallet_adoption_rate = (
            (customers_with_wallets / total_customers * 100)
            if total_customers > 0 else 0
        )

        investment_balances = [
            inv.get('balance', 0) for inv in investment_accounts.values()
        ]
        total_investment_balance = sum(investment_balances)
        avg_investment_balance = (
            statistics.mean(investment_balances) if investment_balances else 0
        )

        customers_with_investments = len(investment_accounts)
        investment_adoption_rate = (
            (customers_with_investments / total_customers * 100)
            if total_customers > 0 else 0
        )

        customer_transactions: Dict[str, int] = defaultdict(int)
        customer_transaction_volume: Dict[str, float] = defaultdict(float)
        for tx in transaction_ledger.values():
            customer_id = tx.get('customer_id')
            if customer_id is None:
                continue
            customer_transactions[customer_id] += 1
            customer_transaction_volume[customer_id] += abs(tx.get('amount', 0))

        avg_transactions_per_customer = (
            sum(customer_transactions.values()) / len(customer_transactions)
        ) if customer_transactions else 0

        customers_with_policies = len(
            {p.get('customer_id') for p in policies.values() if p.get('customer_id')}
        )
        policy_adoption_rate = (
            (customers_with_policies / total_customers * 100)
            if total_customers > 0 else 0
        )

        top_customers = sorted(
            customer_transaction_volume.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:10]
        top_customers_data = [
            {
                'customer_id': cust_id,
                'transaction_volume': round(volume, 2),
                'transaction_count': customer_transactions.get(cust_id, 0),
                'wallet_balance': health_wallets.get(cust_id, {}).get('balance', 0),
                'investment_balance': investment_accounts.get(cust_id, {}).get('balance', 0),
            }
            for cust_id, volume in top_customers
        ]

        return {
            'summary': {
                'total_customers': total_customers,
                'customers_with_wallets': customers_with_wallets,
                'customers_with_investments': customers_with_investments,
                'customers_with_policies': customers_with_policies,
            },
            'wallet_analytics': {
                'total_balance': round(total_wallet_balance, 2),
                'avg_balance': round(avg_wallet_balance, 2),
                'adoption_rate': round(wallet_adoption_rate, 2),
            },
            'investment_analytics': {
                'total_balance': round(total_investment_balance, 2),
                'avg_balance': round(avg_investment_balance, 2),
                'adoption_rate': round(investment_adoption_rate, 2),
            },
            'transaction_analytics': {
                'avg_transactions_per_customer': round(
                    avg_transactions_per_customer, 2
                ),
                'total_transactions': sum(customer_transactions.values()),
            },
            'policy_adoption_rate': round(policy_adoption_rate, 2),
            'top_customers': top_customers_data,
        }

    def get_supplier_analytics(
        self,
        suppliers: Dict[str, Any],
        supplier_orders: Dict[str, Any],
        supplier_metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Analyze supplier ecosystem performance (cached, BI-2)."""
        fingerprint = self._fingerprint(suppliers, supplier_orders, supplier_metrics)
        return self._cached(
            'supplier_analytics',
            fingerprint,
            lambda: self._compute_supplier_analytics(
                suppliers, supplier_orders, supplier_metrics,
            ),
        )

    def _compute_supplier_analytics(
        self,
        suppliers: Dict[str, Any],
        supplier_orders: Dict[str, Any],
        supplier_metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        total_suppliers = len(suppliers)

        status_breakdown: Dict[str, int] = defaultdict(int)
        category_breakdown: Dict[str, int] = defaultdict(int)
        for supplier in suppliers.values():
            status_breakdown[supplier.get('status', 'unknown')] += 1
            category_breakdown[supplier.get('category', 'unknown')] += 1

        active_suppliers = status_breakdown.get('approved', 0)
        pending_suppliers = status_breakdown.get('pending', 0)

        total_orders = len(supplier_orders)
        orders_by_status: Dict[str, int] = defaultdict(int)
        total_order_value = 0.0
        for order in supplier_orders.values():
            orders_by_status[order.get('status', 'unknown')] += 1
            total_order_value += order.get('total_amount', 0)
        avg_order_value = total_order_value / total_orders if total_orders > 0 else 0

        supplier_ratings = [m.get('rating', 0) for m in supplier_metrics.values()]
        avg_supplier_rating = (
            statistics.mean(supplier_ratings) if supplier_ratings else 0
        )

        top_suppliers = sorted(
            supplier_metrics.items(),
            key=lambda x: x[1].get('total_revenue', 0),
            reverse=True,
        )[:10]
        top_suppliers_data = [
            {
                'supplier_id': sup_id,
                'total_revenue': metrics.get('total_revenue', 0),
                'total_orders': metrics.get('total_deliveries', 0),
                'rating': metrics.get('rating', 0),
                'reliability_score': metrics.get('reliability_score', 0),
            }
            for sup_id, metrics in top_suppliers
        ]

        return {
            'summary': {
                'total_suppliers': total_suppliers,
                'active_suppliers': active_suppliers,
                'pending_approval': pending_suppliers,
                'avg_supplier_rating': round(avg_supplier_rating, 2),
            },
            'status_breakdown': dict(status_breakdown),
            'category_breakdown': dict(category_breakdown),
            'orders': {
                'total_orders': total_orders,
                'total_order_value': round(total_order_value, 2),
                'avg_order_value': round(avg_order_value, 2),
                'orders_by_status': dict(orders_by_status),
            },
            'top_suppliers': top_suppliers_data,
        }

    # ------------------------------------------------------------------
    # AI insights and forecasting
    # ------------------------------------------------------------------

    @instrument_agent('bi_analytics')
    def generate_ai_insights(
        self,
        dashboard_data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Generate AI-powered insights and recommendations."""
        insights: List[Dict[str, Any]] = []
        financial = dashboard_data.get('financial', {}) or {}
        claims = dashboard_data.get('claims', {}) or {}

        loss_ratio = financial.get('loss_ratio', 0)
        if loss_ratio > 80:
            insights.append({
                'category': 'financial',
                'severity': 'high',
                'title': 'High Loss Ratio Detected',
                'description': f'Loss ratio is {loss_ratio:.1f}%, exceeding healthy threshold of 80%',
                'recommendation': (
                    'Consider: 1) Premium rate adjustments, '
                    '2) Stricter underwriting criteria, '
                    '3) Claims review process'
                ),
                'impact': 'Sustainable profitability at risk',
            })
        elif loss_ratio > 60:
            insights.append({
                'category': 'financial',
                'severity': 'medium',
                'title': 'Elevated Loss Ratio',
                'description': f'Loss ratio is {loss_ratio:.1f}%, approaching cautionary threshold',
                'recommendation': 'Monitor claims trends closely and review premium pricing',
                'impact': 'Profit margins may be compressed',
            })

        approval_rate = claims.get('approval_rate', 0)
        if approval_rate < 50:
            insights.append({
                'category': 'operations',
                'severity': 'medium',
                'title': 'Low Claims Approval Rate',
                'description': f'Only {approval_rate:.1f}% of claims are approved',
                'recommendation': (
                    'Review claims adjudication process for efficiency and customer satisfaction'
                ),
                'impact': 'Customer satisfaction and retention risk',
            })

        outstanding = financial.get('outstanding_receivables', 0)
        annual_revenue = (
            dashboard_data.get('summary', {}).get('annual_revenue_projection', 0)
        )
        if annual_revenue > 0:
            receivables_ratio = (outstanding / annual_revenue) * 100
            if receivables_ratio > 10:
                insights.append({
                    'category': 'financial',
                    'severity': 'medium',
                    'title': 'High Outstanding Receivables',
                    'description': (
                        f'Outstanding receivables are {receivables_ratio:.1f}% '
                        'of annual revenue'
                    ),
                    'recommendation': (
                        'Implement automated payment reminders and collection procedures'
                    ),
                    'impact': 'Cash flow constraints',
                })

        net_worth = financial.get('net_worth', 0)
        if net_worth < 0:
            insights.append({
                'category': 'financial',
                'severity': 'critical',
                'title': 'Negative Net Worth',
                'description': f'Net worth is negative: ${net_worth:,.2f}',
                'recommendation': (
                    'URGENT: Capital injection required, reduce liabilities, increase revenue'
                ),
                'impact': 'Company solvency at risk',
            })

        health_scores = dashboard_data.get('health_scores', {}) or {}
        overall_health = health_scores.get('overall_health', 0)
        if overall_health >= 80:
            insights.append({
                'category': 'success',
                'severity': 'positive',
                'title': 'Strong Overall Health',
                'description': f'Platform health score: {overall_health:.1f}/100',
                'recommendation': 'Maintain current strategies and consider growth initiatives',
                'impact': 'Strong foundation for expansion',
            })
        elif overall_health < 50:
            insights.append({
                'category': 'operations',
                'severity': 'high',
                'title': 'Low Platform Health Score',
                'description': f'Overall health score: {overall_health:.1f}/100',
                'recommendation': (
                    'Conduct comprehensive review of operations, financials, and customer satisfaction'
                ),
                'impact': 'Platform sustainability concerns',
            })

        return insights

    def predict_revenue_forecast(
        self,
        policies: Dict[str, Any],
        historical_growth_rate: Optional[float] = FORECAST_DEFAULT_MONTHLY_GROWTH,
        months_ahead: int = 12,
        lapse_rate_year1: Optional[float] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Predict revenue forecast for the next N months (cached, B10).

        ``forecast`` keeps its historical meaning — deterministic compounding
        of current MRR at ``growth_rate`` with no churn — so existing consumers
        are unchanged. Two additive blocks make the forecast honest:

        * ``forecast_basis`` says where the growth rate came from. Pass
          ``historical_growth_rate=None`` to derive it from observed policy
          start dates; that only happens with at least
          ``FORECAST_MIN_HISTORY_MONTHS`` complete months of history, otherwise
          the default applies and the basis says so.
        * ``bands`` gives p10/p50/p90 per month, net of the lapse-table
          year-1 churn, using a closed-form log-normal random walk in monthly
          growth (no RNG, so the result is reproducible for the same inputs).

        The result carries ``computed_at``. The route's default request
        (``historical_growth_rate=None``, 12 months) is the ``revenue_forecast``
        materialized view a scheduler can precompute; other parameter sets are
        cached under their own key. The fingerprint includes the live lapse
        rate, so an actuarial table promotion invalidates the forecast too.
        Passing ``now`` bypasses the cache (test/what-if use).
        """
        if now is not None:
            return self._compute_revenue_forecast(
                policies, historical_growth_rate, months_ahead, lapse_rate_year1, now)
        if lapse_rate_year1 is None:
            lapse_basis = _lapse_rate_year1_from_store()
        else:
            lapse_basis = (lapse_rate_year1, 'caller_parameter')
        params = {'growth': historical_growth_rate, 'months': int(months_ahead), 'lapse': list(lapse_basis)}
        is_default = historical_growth_rate is None and int(months_ahead) == 12 and lapse_rate_year1 is None
        key = 'revenue_forecast' if is_default else 'revenue_forecast:custom'
        return self._cached(
            key,
            self._fingerprint(policies, params),
            lambda: self._compute_revenue_forecast(
                policies, historical_growth_rate, months_ahead, lapse_rate_year1, None),
        )

    def _compute_revenue_forecast(
        self,
        policies: Dict[str, Any],
        historical_growth_rate: Optional[float],
        months_ahead: int,
        lapse_rate_year1: Optional[float],
        now: Optional[datetime],
    ) -> Dict[str, Any]:
        current_mrr = sum(
            p.get('monthly_premium', 0)
            for p in policies.values()
            if p.get('status') == 'active'
        )

        observed = observed_monthly_growth(policies, now=now)
        if historical_growth_rate is None:
            if observed['sufficient']:
                growth_rate = float(observed['monthly_growth'])
                growth_source = 'observed_policy_start_dates'
            else:
                growth_rate = FORECAST_DEFAULT_MONTHLY_GROWTH
                growth_source = 'default_insufficient_history'
        else:
            growth_rate = float(historical_growth_rate)
            growth_source = 'caller_parameter'

        if lapse_rate_year1 is None:
            lapse_rate_year1, churn_source = _lapse_rate_year1_from_store()
        else:
            churn_source = 'caller_parameter'
        lapse_rate_year1 = min(max(kpi._num(lapse_rate_year1), 0.0), 1.0)
        monthly_churn = 1.0 - (1.0 - lapse_rate_year1) ** (1.0 / 12.0)

        if observed['sufficient'] and observed.get('monthly_growth_sd') is not None:
            growth_sd = float(observed['monthly_growth_sd'])
            sd_source = 'observed_month_to_month_growth'
        else:
            growth_sd = FORECAST_DEFAULT_MONTHLY_GROWTH_SD
            sd_source = 'default'
        net_growth = growth_rate - monthly_churn
        z90 = 1.2815515655446004  # one-sided 90 % normal quantile → p10 / p90

        forecast = []
        bands = []
        for month in range(1, months_ahead + 1):
            forecasted_mrr = current_mrr * ((1 + growth_rate) ** month)
            forecast.append({
                'month': month,
                'forecasted_mrr': round(forecasted_mrr, 2),
                'forecasted_arr': round(forecasted_mrr * 12, 2),
            })
            median = current_mrr * max(0.0, 1 + net_growth) ** month
            spread = math.exp(z90 * growth_sd * math.sqrt(month))
            bands.append({
                'month': month,
                'p10': round(median / spread, 2),
                'p50': round(median, 2),
                'p90': round(median * spread, 2),
            })

        return {
            'current_mrr': round(current_mrr, 2),
            'current_arr': round(current_mrr * 12, 2),
            'growth_rate': growth_rate * 100,
            'forecast_months': months_ahead,
            'forecast': forecast,
            'forecast_basis': {
                'growth_rate_source': growth_source,
                'monthly_growth_rate': round(growth_rate, 6),
                'observed_history_months': observed['history_months'],
                'min_history_months': FORECAST_MIN_HISTORY_MONTHS,
                'observed_monthly_growth': observed.get('monthly_growth'),
                'observed_growth_window_months': observed.get('window_months'),
                'lapse_rate_year1': round(lapse_rate_year1, 6),
                'monthly_churn': round(monthly_churn, 6),
                'churn_source': churn_source,
                'net_monthly_growth': round(net_growth, 6),
                'monthly_growth_sd': round(growth_sd, 6),
                'growth_sd_source': sd_source,
                'point_forecast': 'current_mrr × (1 + growth_rate)^month, no churn (legacy basis)',
                'bands': 'p50 = current_mrr × (1 + growth_rate − monthly_churn)^month; '
                         'p10/p90 = p50 × exp(∓1.2816 × sd × √month)',
            },
            'bands': bands,
        }

    # ------------------------------------------------------------------
    # Experience slices (read-only, real data)
    # ------------------------------------------------------------------

    def get_loss_ratio_by_smoking_status(
        self,
        customers: Dict[str, Any],
        policies: Dict[str, Any],
        claims: Dict[str, Any],
        underwriting_applications: Optional[Dict[str, Any]] = None,
        pricing_factors: Optional[Dict[str, Any]] = None,
        min_lives: int = SMOKING_SLICE_MIN_LIVES,
    ) -> Dict[str, Any]:
        """Cached wrapper around :func:`loss_ratio_by_smoking_status`."""
        fingerprint = self._fingerprint(
            customers, policies, claims, underwriting_applications or {}, pricing_factors or {}, min_lives
        )
        return self._cached(
            'loss_ratio_by_smoking_status',
            fingerprint,
            lambda: loss_ratio_by_smoking_status(
                customers, policies, claims,
                underwriting_applications=underwriting_applications,
                pricing_factors=pricing_factors,
                min_lives=min_lives,
            ),
        )

    # ------------------------------------------------------------------
    # Health score helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_financial_health_score(
        balance_sheet: Dict[str, Any],
        monthly_revenue: float,
        claims_paid: float,
    ) -> float:
        score = 50.0
        net_worth = (
            balance_sheet.get('total_assets', 0)
            - balance_sheet.get('total_liabilities', 0)
        )
        if net_worth > 0:
            score += min(30.0, (net_worth / 100000) * 10)
        claims_reserve = balance_sheet.get('claims_reserve', 0)
        if monthly_revenue > 0:
            reserve_ratio = claims_reserve / (monthly_revenue * 3)
            score += min(30.0, reserve_ratio * 30)
        if monthly_revenue > 0:
            score += 20.0
        return min(100.0, max(0.0, round(score, 2)))

    @staticmethod
    def _calculate_operational_health_score(
        claims_approval_rate: float,
        outstanding_receivables: float,
        annual_revenue: float,
    ) -> float:
        score = 50.0
        if claims_approval_rate >= 70:
            score += 30.0
        elif claims_approval_rate >= 50:
            score += 20.0
        elif claims_approval_rate >= 30:
            score += 10.0
        if annual_revenue > 0:
            receivables_ratio = outstanding_receivables / annual_revenue
            if receivables_ratio < 0.05:
                score += 20.0
            elif receivables_ratio < 0.10:
                score += 15.0
            elif receivables_ratio < 0.20:
                score += 10.0
        return min(100.0, max(0.0, round(score, 2)))


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------


_bi_analytics_service: Optional[BIAnalyticsService] = None


def get_bi_analytics_service() -> BIAnalyticsService:
    """Get or create the BI analytics service singleton."""
    global _bi_analytics_service
    if _bi_analytics_service is None:
        _bi_analytics_service = BIAnalyticsService()
    return _bi_analytics_service


def init_bi_analytics_service(*_args, **_kwargs) -> BIAnalyticsService:
    """
    Backward-compatible initializer. Older call sites passed data-store
    references here; the current service reads its inputs per-call (see
    PHINS_PLATFORM_ASSESSMENT.md §2.1 on why), so the arguments are accepted
    and ignored. Returns the singleton.
    """
    global _bi_analytics_service
    _bi_analytics_service = BIAnalyticsService()
    return _bi_analytics_service


# ---------------------------------------------------------------------------
# Agent runtime registration (discovery + health only; no behaviour change).
# ---------------------------------------------------------------------------
def _bi_analytics_health() -> Dict[str, Any]:
    """Read-only probe: never instantiates the service."""
    instance = _bi_analytics_service
    if instance is None:
        return {'status': 'ok', 'initialized': False}
    payload: Dict[str, Any] = {'status': 'ok', 'initialized': True}
    try:
        payload.update(instance.describe())
    except Exception as exc:  # the probe must never fail because of diagnostics
        payload['cache_ttl_seconds'] = getattr(instance, 'cache_ttl_seconds', None)
        payload['describe_error'] = str(exc)
    return payload


# Store names (DatabaseDict repository names) whose rows feed a BI view.
BI_INPUT_REPOSITORIES = frozenset({'customers', 'policies', 'claims', 'billing', 'underwriting'})


def _on_store_write(repository_name: str, operation: str) -> None:
    """DatabaseDict write listener: forwards BI-relevant writes to the singleton.

    Registered once at import; a service created later still receives the
    notifications because the forward resolves the singleton at call time.
    """
    if repository_name not in BI_INPUT_REPOSITORIES:
        return
    instance = _bi_analytics_service
    if instance is not None:
        instance.notify_data_change(repository_name)


def notify_bi_data_change(store: str = '*') -> Optional[int]:
    """Module-level write hook for in-memory stores (``save_ledger_data`` etc.).

    Cheap no-op until the singleton exists; never raises into a write path.
    """
    instance = _bi_analytics_service
    if instance is None:
        return None
    try:
        return instance.notify_data_change(store)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("BI data-change notification failed: %s", exc)
        return None


try:
    from database import data_access as _data_access
    _data_access.add_write_listener(_on_store_write)
except Exception as _listener_exc:  # pragma: no cover - DB layer absent
    logger.debug("BI write listener not attached: %s", _listener_exc)


try:
    from services.agent_runtime import AgentDescriptor as _AgentDescriptor, register as _register_agent
    _register_agent(_AgentDescriptor(
        id='bi_analytics',
        name='BI Analytics & Insights',
        version='1.0.0',
        module=__name__,
        description=(
            'Executive, delivery, customer, and supplier dashboards plus '
            'rule-based AI insights and revenue forecasting.'
        ),
        entry_url='/admin.html',
        api={'method': 'GET', 'path': '/api/bi/insights'},
        roles=('admin', 'accountant', 'underwriter'),
        deterministic=True,
        sample_prompts=(
            'What are the current BI insights?',
            'Forecast revenue for the next 6 months',
        ),
    ), health_fn=_bi_analytics_health)
except Exception as _reg_exc:  # pragma: no cover
    logger.warning("BI analytics agent registration skipped: %s", _reg_exc)


__all__ = [
    'AlertSeverity',
    'BIAnalyticsService',
    'BIInsight',
    'KPIMetric',
    'MetricCategory',
    'StatisticalSummary',
    'TrendDirection',
    'VIEW_SCHEMA_VERSION',
    'BI_INPUT_REPOSITORIES',
    'get_bi_analytics_service',
    'init_bi_analytics_service',
    'notify_bi_data_change',
]
