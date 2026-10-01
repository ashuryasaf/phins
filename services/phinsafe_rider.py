"""PhinSafe — child catastrophe-hedge rider.

PhinSafe attaches to a parent who has joined PHINS. It is a permanent
settlement: the benefit locked at issue is one fifth of the insured benefit
on each attached parent policy, and it does not move if that face changes
later. The parent must join at or under a community maximum age, and that
maximum is strictly below the portfolio simulator's maximum age. A first
pregnancy is covered only when it begins on or after the first anniversary
of the join date.

The testing book is not a second random portfolio. It is a deterministic
slice of a published simulation: parents inside the age window, scaled by
an adjustable market share, then scaled by 1/5. Money is integer cents.
A projection that cannot prove its identities is refused.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


PRODUCT_ID = 'phinsafe'
PRODUCT_NAME = 'PhinSafe'
BENEFIT_NUMERATOR = 1
BENEFIT_DENOMINATOR = 5
WAITING_YEARS = 1
SETTLEMENT = 'permanent'
PARENT_MIN_JOIN_AGE = 18
SHARE_SCALE = 10_000  # 100.00% -> 10000
BOOK_EVENT = 'phinsafe_book_anchored'
RIDER_EVENT = 'phinsafe_rider_bound'
CLAIM_EVENT = 'phinsafe_claim_opened'
LEDGER_ENTITY = 'phinsafe_rider'
SOURCE_SYSTEM = 'phinsafe'


class PhinSafeIntegrityError(ValueError):
    """Fail-closed refusal. Nothing downstream may treat this as a book."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = int(status)


@dataclass(frozen=True)
class CommunityProgram:
    community_id: str
    label: str
    max_joining_age: int
    weight_units: int  # 10000 = 100% of eligible parents


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def document_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode('utf-8')).hexdigest()


def _entry_id(prefix: str, material: str, limit: int = 120) -> str:
    """Stable id. Ledger ids fit in 120 characters; bills and claims fit in 50."""
    digest = hashlib.sha256(material.encode('utf-8')).hexdigest()
    room = int(limit) - len(prefix) - 1
    if room < 16:
        raise PhinSafeIntegrityError('identifier prefix does not fit the column')
    return f'{prefix}-{digest[:room]}'


def money_cents(value: Any) -> int:
    """Round a dollar amount to integer cents. Refuses non-finite input."""
    try:
        dec = Decimal(str(value))
    except Exception as exc:
        raise PhinSafeIntegrityError(f'invalid money amount: {value}') from exc
    if not dec.is_finite():
        raise PhinSafeIntegrityError('money amount must be finite')
    quantized = dec.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return int(quantized * 100)


def cents_to_dollars(cents: int) -> float:
    return int(cents) / 100.0


def _parse_date(value: Any, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or '').strip()
    if not text:
        raise PhinSafeIntegrityError(f'{field} is required')
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise PhinSafeIntegrityError(f'{field} must be an ISO date') from exc


def add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + int(years))
    except ValueError:
        return day.replace(year=day.year + int(years), day=28)


def age_on(dob: date, on_day: date) -> int:
    years = on_day.year - dob.year
    if (on_day.month, on_day.day) < (dob.month, dob.day):
        years -= 1
    return years


def share_units(market_share_pct: Any) -> int:
    try:
        dec = Decimal(str(market_share_pct))
    except Exception as exc:
        raise PhinSafeIntegrityError('market share must be a number') from exc
    if not dec.is_finite():
        raise PhinSafeIntegrityError('market share must be finite')
    quantized = dec.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if quantized < 0 or quantized > 100:
        raise PhinSafeIntegrityError('market share must be between 0 and 100')
    return int(quantized * 100)


def weight_units(member_weight_pct: Any) -> int:
    try:
        dec = Decimal(str(member_weight_pct))
    except Exception as exc:
        raise PhinSafeIntegrityError('community member weight must be a number') from exc
    quantized = dec.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if quantized <= 0 or quantized > 100:
        raise PhinSafeIntegrityError('community member weight must be between 0 and 100')
    return int(quantized * 100)


def _scale(cents: int, numer: int, denom: int) -> int:
    if cents < 0 or numer < 0 or denom <= 0:
        raise PhinSafeIntegrityError('cannot scale a negative amount')
    return (int(cents) * int(numer)) // int(denom)


def rider_scale(cents: int, units: int) -> int:
    """Market share, then exactly one fifth. Truncates a fraction of a cent."""
    return _scale(int(cents), int(units), SHARE_SCALE * BENEFIT_DENOMINATOR)


def contract_terms() -> Dict[str, Any]:
    return {
        'product_id': PRODUCT_ID,
        'product_name': PRODUCT_NAME,
        'designation': 'child catastrophe hedge for parents-to-be',
        'basis': 'risk_plus_savings_add_on',
        'settlement': SETTLEMENT,
        'benefit_fraction': f'{BENEFIT_NUMERATOR}/{BENEFIT_DENOMINATOR}',
        'benefit_rule': (
            'The settled benefit on each attached parent policy is one fifth '
            'of that policy\'s insured benefit at issue. Policies are not pooled '
            'before the fraction is applied.'
        ),
        'waiting_years': WAITING_YEARS,
        'waiting_rule': (
            'The parent joins under a permanent settlement. A first pregnancy '
            'is covered only when it begins on or after the first anniversary '
            'of the join date. Premium is due during the waiting year. The '
            'benefit stays locked after settlement.'
        ),
        'parent_min_join_age': PARENT_MIN_JOIN_AGE,
        'age_rule': (
            'Each community sets the maximum age at which a parent may join. '
            'That maximum must be strictly below the portfolio simulator '
            'maximum age used to price the book. Parents younger than '
            f'{PARENT_MIN_JOIN_AGE} are not eligible.'
        ),
    }


def _money_rows(simulation: Mapping[str, Any]) -> List[Dict[str, Any]]:
    integrity = simulation.get('accepted_money_integrity') or {}
    if integrity and not integrity.get('all_checks_pass'):
        raise PhinSafeIntegrityError(
            'simulation per-age money ledger failed its own integrity checks',
            status=409,
        )
    rows = simulation.get('accepted_money_by_age')
    if not isinstance(rows, list) or not rows:
        raise PhinSafeIntegrityError(
            'simulation has no per-age money ledger; re-run the portfolio simulator',
            status=409,
        )
    return [dict(row) for row in rows]


def _histogram_accepted(simulation: Mapping[str, Any]) -> Dict[int, int]:
    matrix = simulation.get('age_adl_matrix') or {}
    distribution = matrix.get('distribution') or {}
    histogram = distribution.get('histogram') or []
    counts: Dict[int, int] = {}
    for row in histogram:
        try:
            age = int(row.get('age'))
            accepted = int(row.get('accepted') or 0)
        except (TypeError, ValueError) as exc:
            raise PhinSafeIntegrityError('simulation age histogram is not numeric') from exc
        counts[age] = counts.get(age, 0) + accepted
    return counts


def _portfolio_totals(simulation: Mapping[str, Any]) -> Dict[str, int]:
    summary = simulation.get('portfolio_summary') or {}
    try:
        accepted = int(summary.get('accepted_customers') or 0)
    except (TypeError, ValueError) as exc:
        raise PhinSafeIntegrityError('simulation accepted count is not numeric') from exc
    return {
        'accepted': accepted,
        'coverage': money_cents(summary.get('total_coverage') or 0),
        'annual_premium': money_cents(summary.get('total_annual_premium') or 0),
        'risk_premium': money_cents(summary.get('total_risk_premium') or 0),
        'savings_premium': money_cents(summary.get('total_savings_premium') or 0),
    }


def _row_cents(row: Mapping[str, Any]) -> Dict[str, int]:
    try:
        accepted = int(row.get('accepted') or 0)
        term_years = int(row.get('term_years') or 0)
        age = int(row.get('age'))
    except (TypeError, ValueError) as exc:
        raise PhinSafeIntegrityError('per-age money ledger has a non-numeric count') from exc
    if accepted < 0 or term_years < 0:
        raise PhinSafeIntegrityError('per-age money ledger has a negative count')
    return {
        'age': age,
        'accepted': accepted,
        'term_years': term_years,
        'coverage': money_cents(row.get('coverage') or 0),
        'annual_premium': money_cents(row.get('annual_premium') or 0),
        'risk_premium': money_cents(row.get('risk_premium') or 0),
        'savings_premium': money_cents(row.get('savings_premium') or 0),
        'pv_mortality': money_cents(row.get('pv_mortality') or 0),
        'pv_disability': money_cents(row.get('pv_disability') or 0),
        'expected_claims_year1': money_cents(row.get('expected_claims_year1') or 0),
    }


_MONEY_KEYS = (
    'coverage', 'annual_premium', 'risk_premium', 'savings_premium',
    'pv_mortality', 'pv_disability', 'expected_claims_year1',
)


def _sum_rows(rows: Sequence[Mapping[str, int]]) -> Dict[str, int]:
    total = {key: 0 for key in _MONEY_KEYS}
    total['accepted'] = 0
    total['term_years'] = 0
    for row in rows:
        total['accepted'] += int(row['accepted'])
        total['term_years'] += int(row['term_years'])
        for key in _MONEY_KEYS:
            total[key] += int(row[key])
    return total


def _empty_bucket() -> Dict[str, int]:
    bucket = {key: 0 for key in _MONEY_KEYS}
    bucket['accepted'] = 0
    bucket['term_years'] = 0
    return bucket


def _add_bucket(into: Dict[str, int], row: Mapping[str, int]) -> None:
    into['accepted'] += int(row['accepted'])
    into['term_years'] += int(row['term_years'])
    for key in _MONEY_KEYS:
        into[key] += int(row[key])


def parse_communities(
    raw: Optional[Sequence[Mapping[str, Any]]],
    *,
    parent_max_age: int,
    simulator_age_max: int,
) -> List[CommunityProgram]:
    if not raw:
        return [CommunityProgram(
            community_id='all-communities',
            label='All communities',
            max_joining_age=int(parent_max_age),
            weight_units=SHARE_SCALE,
        )]
    programs: List[CommunityProgram] = []
    seen = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise PhinSafeIntegrityError('each community program must be an object')
        community_id = str(item.get('community_id') or '').strip()
        if not community_id or len(community_id) > 64:
            raise PhinSafeIntegrityError('community_id is required and must be at most 64 characters')
        if any(ch not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for ch in community_id):
            raise PhinSafeIntegrityError('community_id may contain only letters, numbers, hyphen and underscore')
        if community_id in seen:
            raise PhinSafeIntegrityError(f'duplicate community_id: {community_id}')
        seen.add(community_id)
        try:
            cap = int(item.get('max_joining_age'))
        except (TypeError, ValueError) as exc:
            raise PhinSafeIntegrityError(f'{community_id} max joining age must be an integer') from exc
        if cap < PARENT_MIN_JOIN_AGE:
            raise PhinSafeIntegrityError(
                f'{community_id} max joining age must be at least {PARENT_MIN_JOIN_AGE}'
            )
        if cap > int(parent_max_age):
            raise PhinSafeIntegrityError(
                f'{community_id} max joining age cannot exceed the PhinSafe parent maximum'
            )
        if cap >= int(simulator_age_max):
            raise PhinSafeIntegrityError(
                f'{community_id} max joining age must be below the simulator maximum age'
            )
        label = str(item.get('label') or community_id).strip()[:80] or community_id
        programs.append(CommunityProgram(
            community_id=community_id,
            label=label,
            max_joining_age=cap,
            weight_units=weight_units(item.get('member_weight_pct')),
        ))
    if sum(program.weight_units for program in programs) != SHARE_SCALE:
        raise PhinSafeIntegrityError('community member weights must sum to 100')
    return programs


def _covering(programs: Sequence[CommunityProgram], age: int) -> List[int]:
    return [
        index for index, program in enumerate(programs)
        if PARENT_MIN_JOIN_AGE <= age <= program.max_joining_age
    ]


def _allocate_integer(
    total: int,
    programs: Sequence[CommunityProgram],
    *,
    age: int,
) -> List[int]:
    """Split an integer across communities that cover this age.

    Weights are shares of the parent population. A community that does not
    cover the age does not receive it, and its weight is not given to the
    communities that do. Largest remainder keeps the sum exact.
    """
    amounts = [0] * len(programs)
    covering = _covering(programs, age)
    total = int(total)
    if total <= 0 or not covering:
        return amounts
    covered_weight = sum(programs[index].weight_units for index in covering)
    pool = (total * covered_weight) // SHARE_SCALE
    floors: List[int] = []
    remainders: List[Tuple[int, int]] = []
    for index in covering:
        numer = total * programs[index].weight_units
        floors.append(numer // SHARE_SCALE)
        remainders.append((numer % SHARE_SCALE, index))
    leftover = pool - sum(floors)
    if leftover < 0 or leftover > len(covering):
        raise PhinSafeIntegrityError('community allocation remainder is outside its bounds')
    order = sorted(remainders, key=lambda item: (-item[0], item[1]))
    bonus = {index: 0 for index in covering}
    for step in range(leftover):
        bonus[order[step][1]] += 1
    for offset, index in enumerate(covering):
        amounts[index] = floors[offset] + bonus[index]
    if sum(amounts) != pool:
        raise PhinSafeIntegrityError('community allocation does not sum to the covered pool')
    return amounts


def _dollars_from_bucket(bucket: Mapping[str, int]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        'accepted_parents': int(bucket['accepted']),
        'term_years': int(bucket['term_years']),
    }
    for key in _MONEY_KEYS:
        out[key] = cents_to_dollars(int(bucket[key]))
        out[f'{key}_cents'] = int(bucket[key])
    annual = int(bucket['annual_premium'])
    risk = int(bucket['risk_premium'])
    savings = int(bucket['savings_premium'])
    loading = annual - risk - savings
    out['expense_and_profit'] = cents_to_dollars(loading)
    out['expense_and_profit_cents'] = loading
    out['components_sum_to_premium'] = (risk + savings + loading) == annual
    return out


def project_book(
    simulation: Mapping[str, Any],
    *,
    parent_max_age: int,
    market_share_pct: Any,
    communities: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build the PhinSafe testing book from one published simulation."""
    params = simulation.get('parameters') or {}
    try:
        simulator_age_max = int(params.get('age_max'))
    except (TypeError, ValueError) as exc:
        raise PhinSafeIntegrityError('simulation is missing age_max') from exc
    try:
        cap = int(parent_max_age)
    except (TypeError, ValueError) as exc:
        raise PhinSafeIntegrityError('parent maximum age must be an integer') from exc
    if cap < PARENT_MIN_JOIN_AGE:
        raise PhinSafeIntegrityError(
            f'parent maximum age must be at least {PARENT_MIN_JOIN_AGE}'
        )
    if cap >= simulator_age_max:
        raise PhinSafeIntegrityError(
            'PhinSafe parent maximum age must be lower than the simulator maximum age'
        )
    units = share_units(market_share_pct)
    programs = parse_communities(
        communities,
        parent_max_age=cap,
        simulator_age_max=simulator_age_max,
    )

    source_rows = _money_rows(simulation)
    raw_rows = [_row_cents(row) for row in source_rows]
    histogram = _histogram_accepted(simulation)
    portfolio = _portfolio_totals(simulation)
    ledger = _sum_rows(raw_rows)
    summary = simulation.get('portfolio_summary') or {}

    def _close(left: float, right: float) -> bool:
        return abs(float(left) - float(right)) <= 0.02

    raw_coverage = sum(float(row.get('coverage') or 0) for row in source_rows)
    raw_annual = sum(float(row.get('annual_premium') or 0) for row in source_rows)
    raw_risk = sum(float(row.get('risk_premium') or 0) for row in source_rows)
    raw_savings = sum(float(row.get('savings_premium') or 0) for row in source_rows)

    histogram_ok = all(
        int(row['accepted']) == int(histogram.get(int(row['age']), -1))
        for row in raw_rows
    )
    extra_hist = [
        age for age, count in histogram.items()
        if count > 0 and age not in {int(row['age']) for row in raw_rows}
    ]
    counts_ok = ledger['accepted'] == portfolio['accepted'] and not extra_hist
    # Each age row is rounded to cents on its own, so the cent sum can differ
    # from the once-rounded portfolio total by a fraction of a cent per age.
    # The raw sums must still match the portfolio book.
    money_ok = (
        _close(raw_coverage, summary.get('total_coverage') or 0)
        and _close(raw_annual, summary.get('total_annual_premium') or 0)
        and _close(raw_risk, summary.get('total_risk_premium') or 0)
        and _close(raw_savings, summary.get('total_savings_premium') or 0)
    )

    eligible_rows = [
        row for row in raw_rows
        if PARENT_MIN_JOIN_AGE <= int(row['age']) <= cap
    ]
    below_rows = [row for row in raw_rows if int(row['age']) < PARENT_MIN_JOIN_AGE]
    above_rows = [row for row in raw_rows if int(row['age']) > cap]
    eligible = _sum_rows(eligible_rows)
    below = _sum_rows(below_rows)
    above = _sum_rows(above_rows)
    partition_ok = all(
        eligible[key] + below[key] + above[key] == ledger[key]
        for key in list(_MONEY_KEYS) + ['accepted', 'term_years']
    )

    # Scale each age, then sum. Scaling the total instead would disagree with
    # the community split by up to one cent per age, and the book would no
    # longer add up. The difference from scaling the total is recorded below.
    single = _empty_bucket()
    single['accepted'] = int(eligible['accepted'])
    single['term_years'] = int(eligible['term_years'])
    for row in eligible_rows:
        for key in _MONEY_KEYS:
            single[key] += rider_scale(int(row[key]), units)
    community_buckets = [_empty_bucket() for _ in programs]
    for row in eligible_rows:
        age = int(row['age'])
        for key in _MONEY_KEYS:
            parts = _allocate_integer(rider_scale(int(row[key]), units), programs, age=age)
            for index, amount in enumerate(parts):
                community_buckets[index][key] += amount
        head_parts = _allocate_integer(int(row['accepted']), programs, age=age)
        term_parts = _allocate_integer(int(row['term_years']), programs, age=age)
        for index in range(len(programs)):
            community_buckets[index]['accepted'] += head_parts[index]
            community_buckets[index]['term_years'] += term_parts[index]

    community_sum = _empty_bucket()
    for bucket in community_buckets:
        _add_bucket(community_sum, bucket)
    same_cap = all(program.max_joining_age == cap for program in programs)
    reconcile_keys = list(_MONEY_KEYS) + ['accepted', 'term_years']
    if same_cap:
        communities_match = all(community_sum[key] == single[key] for key in reconcile_keys)
    else:
        communities_match = all(community_sum[key] <= single[key] for key in _MONEY_KEYS)

    single_view = _dollars_from_bucket(single)
    residual = int(single['annual_premium']) - int(single['risk_premium']) - int(single['savings_premium'])
    # Expense and profit are the residual of premium − risk − savings.
    # Scaling those three amounts separately can move the residual by less
    # than one cent per age-year. The published premium still equals
    # risk + savings + residual.
    scaled_loading = 0
    for row in eligible_rows:
        loading_cents = int(row['annual_premium']) - int(row['risk_premium']) - int(row['savings_premium'])
        if loading_cents < 0:
            scaled_loading -= rider_scale(-loading_cents, units)
        else:
            scaled_loading += rider_scale(loading_cents, units)
    age_slots = max(1, len(eligible_rows))
    # Three independently truncated components, so the residual can move by
    # up to two cents per age-year versus scaling the loading itself.
    components_ok = (
        bool(single_view['components_sum_to_premium'])
        and abs(residual - scaled_loading) <= 2 * age_slots
    )
    direct_benefit = rider_scale(int(eligible['coverage']), units)
    benefit_gap = direct_benefit - int(single['coverage'])
    benefit_ok = 0 <= benefit_gap < age_slots
    waiting_ok = WAITING_YEARS == 1 and SETTLEMENT == 'permanent'

    checks = {
        'parent_max_age_below_simulator_max': cap < simulator_age_max,
        'parent_max_age_at_least_minimum': cap >= PARENT_MIN_JOIN_AGE,
        'histogram_counts_match_money_ledger': histogram_ok and counts_ok,
        'money_ledger_matches_portfolio': money_ok,
        'age_window_partitions_the_book': partition_ok,
        'benefit_is_one_fifth_after_market_share': benefit_ok,
        'components_sum_to_premium': components_ok,
        'community_weights_sum_to_100': sum(p.weight_units for p in programs) == SHARE_SCALE,
        'community_caps_inside_product_window': all(
            PARENT_MIN_JOIN_AGE <= p.max_joining_age <= cap < simulator_age_max
            for p in programs
        ),
        'communities_reconcile_to_the_single_book': communities_match,
        'waiting_period_is_one_year': waiting_ok,
        'settlement_is_permanent': SETTLEMENT == 'permanent',
    }
    if not all(checks.values()):
        failed = [name for name, ok in checks.items() if not ok]
        raise PhinSafeIntegrityError(
            'PhinSafe book failed integrity checks: ' + ', '.join(failed),
            status=409,
        )

    simulation_id = str(simulation.get('simulation_id') or '').strip()
    if not simulation_id:
        raise PhinSafeIntegrityError('simulation_id is required')

    community_views = []
    for program, bucket in zip(programs, community_buckets):
        view = _dollars_from_bucket(bucket)
        view.update({
            'community_id': program.community_id,
            'label': program.label,
            'max_joining_age': program.max_joining_age,
            'member_weight_pct': program.weight_units / 100.0,
        })
        community_views.append(view)

    kernel = simulation.get('pricing_kernel') or {}
    book_body = {
        'product_id': PRODUCT_ID,
        'product_name': PRODUCT_NAME,
        'simulation_id': simulation_id,
        'tables_version': simulation.get('tables_version'),
        'contract': contract_terms(),
        'parameters': {
            'simulator_age_max': simulator_age_max,
            'parent_max_age': cap,
            'parent_min_join_age': PARENT_MIN_JOIN_AGE,
            'market_share_pct': units / 100.0,
            'benefit_fraction': f'{BENEFIT_NUMERATOR}/{BENEFIT_DENOMINATOR}',
            'waiting_years': WAITING_YEARS,
            'settlement': SETTLEMENT,
            'savings_rate': kernel.get('savings_rate'),
            'savings_formula': kernel.get('savings_formula'),
        },
        'eligible_parents': {
            'count': eligible['accepted'],
            'coverage': cents_to_dollars(eligible['coverage']),
            'annual_premium': cents_to_dollars(eligible['annual_premium']),
            'risk_premium': cents_to_dollars(eligible['risk_premium']),
            'savings_premium': cents_to_dollars(eligible['savings_premium']),
            'rule': (
                f'Accepted lives with age {PARENT_MIN_JOIN_AGE} through {cap} '
                f'inclusive. Simulator maximum age is {simulator_age_max}.'
            ),
        },
        'excluded': {
            'below_parent_minimum': _dollars_from_bucket(below),
            'above_parent_max_age': _dollars_from_bucket(above),
        },
        'rider_book': single_view,
        'communities': community_views,
        'pricing_identity': {
            'formula': 'each eligible age × market_share × 1/5, then summed',
            'truncation': 'a fraction of a cent is dropped on each age, never rounded up',
            'benefit_gap_cents_versus_scaling_the_total': benefit_gap,
            'premium_residual_cents': residual,
            'loss_ratio_note': (
                'Expected claims scale with the settled benefit, so the rider '
                'loss ratio matches the eligible parent slice.'
            ),
        },
        'connections': {
            'actuarial_book': 'derived from the published simulation money ledger',
            'ledger_event': BOOK_EVENT,
            'policy_attachment': 'each parent policy stores riders.phinsafe',
            'billing': 'separate PhinSafe installment, parent premium unchanged',
            'savings_pipeline': 'savings premium deposits only when the installment is paid',
            'claims': 'pending claim opened against the settled benefit after the waiting year',
        },
    }
    book_body['document_hash'] = document_hash(book_body)
    book_body['integrity'] = {
        'checks': checks,
        'all_checks_pass': True,
        'document_hash': book_body['document_hash'],
    }
    loss = _loss_ratio(single)
    book_body['rider_book']['annual_expected_claims'] = loss['annual_expected_claims']
    book_body['rider_book']['loss_ratio_pct'] = loss['loss_ratio_pct']
    # Hash was taken before the derived loss-ratio fields. Re-hash the
    # published body so the anchor covers the figures the actuary sees.
    published = dict(book_body)
    published.pop('document_hash', None)
    published.pop('integrity', None)
    published['document_hash'] = document_hash(published)
    published['integrity'] = {
        'checks': checks,
        'all_checks_pass': True,
        'document_hash': published['document_hash'],
    }
    return published


def _loss_ratio(scaled: Mapping[str, int]) -> Dict[str, float]:
    pv = int(scaled['pv_mortality']) + int(scaled['pv_disability'])
    term_years = int(scaled['term_years'])
    accepted = int(scaled['accepted'])
    annual_premium = int(scaled['annual_premium'])
    if accepted <= 0 or term_years <= 0 or annual_premium <= 0:
        return {'annual_expected_claims': 0.0, 'loss_ratio_pct': 0.0}
    avg_term = term_years / accepted
    annual_claims_cents = int(round(pv / avg_term))
    ratio = (annual_claims_cents / annual_premium) * 100.0 if annual_premium else 0.0
    return {
        'annual_expected_claims': cents_to_dollars(annual_claims_cents),
        'loss_ratio_pct': round(ratio, 2),
    }


def anchor_book(ledger: Any, book: Mapping[str, Any], *, actor: str) -> Dict[str, Any]:
    """Append the book anchor. Raises if the ledger refuses the write."""
    doc_hash = str(book.get('document_hash') or '')
    simulation_id = str(book.get('simulation_id') or '')
    if not doc_hash or not simulation_id:
        raise PhinSafeIntegrityError('book is missing its document hash', status=409)
    published = {k: v for k, v in book.items() if k not in ('document_hash', 'integrity')}
    if document_hash(published) != doc_hash:
        raise PhinSafeIntegrityError('book document hash does not verify', status=409)
    entry_id = _entry_id('PHINSAFE-BOOK', f'{simulation_id}|{doc_hash}')
    annual = float((book.get('rider_book') or {}).get('annual_premium') or 0)
    try:
        entry = ledger.append_event(
            event_type=BOOK_EVENT,
            entity_type=LEDGER_ENTITY,
            entity_id=simulation_id,
            actor=actor or 'actuary',
            amount=round(annual, 2),
            status='anchored',
            source_system=SOURCE_SYSTEM,
            entry_id=entry_id,
            payload={
                'product_id': PRODUCT_ID,
                'simulation_id': simulation_id,
                'document_hash': doc_hash,
                'parent_max_age': (book.get('parameters') or {}).get('parent_max_age'),
                'market_share_pct': (book.get('parameters') or {}).get('market_share_pct'),
                'simulator_age_max': (book.get('parameters') or {}).get('simulator_age_max'),
                'eligible_parents': (book.get('eligible_parents') or {}).get('count'),
                'rider_annual_premium': annual,
                'benefit_fraction': f'{BENEFIT_NUMERATOR}/{BENEFIT_DENOMINATOR}',
                'waiting_years': WAITING_YEARS,
                'settlement': SETTLEMENT,
            },
        )
    except PhinSafeIntegrityError:
        raise
    except Exception as exc:
        raise PhinSafeIntegrityError(f'ledger refused the PhinSafe book anchor: {exc}', status=503) from exc
    return {
        'entry_id': str(entry.get('id') or entry_id),
        'entry_hash': str(entry.get('entry_hash') or ''),
        'sequence_no': entry.get('sequence_no'),
        'event_type': BOOK_EVENT,
    }


def _policy_savings_cents(policy: Mapping[str, Any], annual_cents: int) -> int:
    """Savings share of the parent premium, as the platform persists it.

    `savings_premium` only exists on in-memory records. An issued policy keeps
    the actuarial pin as `savings_premium_annual` or, failing that, the
    health-wallet allocation percentage of the annual premium.
    """
    for key in ('savings_premium', 'savings_premium_annual'):
        raw = policy.get(key)
        if raw is not None:
            return money_cents(raw)
    wallet = policy.get('health_wallet')
    if isinstance(wallet, str):
        try:
            wallet = json.loads(wallet or '{}')
        except json.JSONDecodeError:
            wallet = {}
    if isinstance(wallet, Mapping) and wallet.get('allocation_percentage') is not None:
        try:
            share = Decimal(str(wallet.get('allocation_percentage')))
        except Exception as exc:
            raise PhinSafeIntegrityError(
                f"policy {policy.get('id') or ''} health wallet allocation is not a number"
            ) from exc
        if not share.is_finite() or share < 0 or share > 100:
            raise PhinSafeIntegrityError(
                f"policy {policy.get('id') or ''} health wallet allocation must be between 0 and 100"
            )
        allocated = (Decimal(int(annual_cents)) * share / Decimal(100)).quantize(
            Decimal('1'), rounding=ROUND_HALF_UP
        )
        return int(allocated)
    return 0


def _policy_money(policy: Mapping[str, Any]) -> Tuple[int, int, int]:
    coverage = policy.get('coverage_amount', policy.get('coverage'))
    annual = policy.get('annual_premium')
    if coverage is None or annual is None:
        raise PhinSafeIntegrityError(
            f"policy {policy.get('id') or ''} is missing coverage or premium"
        )
    coverage_cents = money_cents(coverage)
    annual_cents = money_cents(annual)
    if coverage_cents <= 0 or annual_cents < 0:
        raise PhinSafeIntegrityError(f"policy {policy.get('id') or ''} has no insured benefit")
    savings_cents = _policy_savings_cents(policy, annual_cents)
    if savings_cents > annual_cents:
        raise PhinSafeIntegrityError(
            f"policy {policy.get('id') or ''} savings premium exceeds annual premium"
        )
    return coverage_cents, annual_cents, savings_cents


def _benefit_cents(coverage_cents: int) -> int:
    return int(coverage_cents) // BENEFIT_DENOMINATOR


def customer_dob(customer: Mapping[str, Any]) -> date:
    raw = customer.get('dob') or customer.get('date_of_birth')
    if not raw:
        raise PhinSafeIntegrityError('parent date of birth is required')
    return _parse_date(raw, 'date of birth')


def _existing_rider(policy: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    raw = policy.get('riders')
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or '{}')
        except json.JSONDecodeError:
            raw = {}
    if not isinstance(raw, dict):
        return None
    rider = raw.get(PRODUCT_ID)
    return dict(rider) if isinstance(rider, dict) else None


def _billing_dict(policy: Mapping[str, Any]) -> Dict[str, Any]:
    raw = policy.get('billing')
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or '{}')
        except json.JSONDecodeError:
            raw = {}
    return dict(raw) if isinstance(raw, dict) else {}


def installment_cents(annual_cents: int, month_index: int) -> int:
    """One month of a permanent rider. Twelve months sum to the annual premium."""
    if month_index < 0:
        return 0
    annual_cents = int(annual_cents)
    base = annual_cents // 12
    extra = annual_cents % 12
    if month_index % 12 == 11:
        return base + extra
    return base


def installment_bill_id(rider_id: str, year: int, month: int) -> str:
    return _entry_id('BILL-PS', f'{rider_id}|{int(year):04d}-{int(month):02d}', limit=50)


def _rider_annual_cents(rider: Mapping[str, Any]) -> int:
    """Whole-rider annual premium. A policy stamp carries it as a total."""
    if rider.get('total_annual_premium_cents') is not None:
        return int(rider.get('total_annual_premium_cents') or 0)
    return int(rider.get('annual_premium_cents') or money_cents(rider.get('annual_premium') or 0))


def _rider_savings_cents(rider: Mapping[str, Any]) -> int:
    """Whole-rider savings add-on. A policy stamp carries it as a total."""
    if rider.get('total_savings_premium_cents') is not None:
        return int(rider.get('total_savings_premium_cents') or 0)
    return int(rider.get('savings_premium_cents') or money_cents(rider.get('savings_premium') or 0))


def build_installment(
    rider: Mapping[str, Any],
    *,
    year: int,
    month: int,
) -> Optional[Dict[str, Any]]:
    join = _parse_date(rider.get('join_date'), 'join_date')
    index = (int(year) - join.year) * 12 + (int(month) - join.month)
    if index < 0:
        return None
    annual_cents = _rider_annual_cents(rider)
    savings_cents = _rider_savings_cents(rider)
    amount = installment_cents(annual_cents, index)
    savings = installment_cents(savings_cents, index)
    if amount < savings:
        savings = amount
    rider_id = str(rider.get('rider_id') or '')
    policy_ids = list(rider.get('policy_ids') or [])
    primary = str(rider.get('primary_policy_id') or (policy_ids[0] if policy_ids else ''))
    return {
        'id': installment_bill_id(rider_id, year, month),
        'policy_id': primary,
        'customer_id': rider.get('customer_id'),
        'amount': cents_to_dollars(amount),
        'amount_due': cents_to_dollars(amount),
        'amount_paid': 0.0,
        'status': 'outstanding',
        'type': 'phinsafe_rider',
        'component': PRODUCT_ID,
        'rider_id': rider_id,
        'document_hash': rider.get('document_hash'),
        'due_date': date(int(year), int(month), 1).isoformat(),
        'premium_breakdown': {
            'risk_amount': cents_to_dollars(amount - savings),
            'savings_amount': 0.0,
            'phinsafe_savings_amount': cents_to_dollars(savings),
            'phinsafe_pipeline': 'savings_add_on',
        },
        'savings_fraction': (savings / amount) if amount else 0.0,
    }


def bind_rider(
    *,
    book: Mapping[str, Any],
    customer: Mapping[str, Any],
    policies: Sequence[Mapping[str, Any]],
    community_id: str,
    join_date: Any,
    pregnancy_start: Any = None,
) -> Dict[str, Any]:
    """Settle one PhinSafe rider on the parent's policies. Does not persist."""
    if not (book.get('integrity') or {}).get('all_checks_pass'):
        raise PhinSafeIntegrityError('PhinSafe book is not integrity-cleared', status=409)
    book_hash = str(book.get('document_hash') or '')
    if not book_hash:
        raise PhinSafeIntegrityError('PhinSafe book has no document hash', status=409)
    programs = book.get('communities') or []
    community_id = str(community_id or '').strip()
    program = next((row for row in programs if row.get('community_id') == community_id), None)
    if program is None:
        raise PhinSafeIntegrityError('community is not on the anchored PhinSafe book')
    cap = int(program.get('max_joining_age'))
    joined = _parse_date(join_date, 'join_date')
    parent_age = age_on(customer_dob(customer), joined)
    if parent_age < PARENT_MIN_JOIN_AGE:
        raise PhinSafeIntegrityError(
            f'parent must be at least {PARENT_MIN_JOIN_AGE} on the join date'
        )
    if parent_age > cap:
        raise PhinSafeIntegrityError(
            f'parent age {parent_age} is above the community maximum joining age {cap}'
        )
    customer_id = str(customer.get('id') or customer.get('customer_id') or '').strip()
    if not customer_id:
        raise PhinSafeIntegrityError('customer id is required')
    if not policies:
        raise PhinSafeIntegrityError('at least one parent policy is required')

    coverage_starts = add_years(joined, WAITING_YEARS)
    pregnancy = None
    if pregnancy_start:
        pregnancy = _parse_date(pregnancy_start, 'pregnancy_start')
        if pregnancy < coverage_starts:
            raise PhinSafeIntegrityError(
                'first pregnancy begins during the one-year waiting period'
            )

    slices = []
    benefit_total = 0
    annual_total = 0
    savings_total = 0
    policy_ids: List[str] = []
    for policy in policies:
        policy_id = str(policy.get('id') or '').strip()
        if not policy_id:
            raise PhinSafeIntegrityError('each policy needs an id')
        owner = str(policy.get('customer_id') or '')
        if owner != customer_id:
            raise PhinSafeIntegrityError(f'policy {policy_id} is not owned by this parent')
        status = str(policy.get('status') or '').lower()
        if status not in ('active', 'in_force', 'approved'):
            raise PhinSafeIntegrityError(f'policy {policy_id} is not an in-force parent policy')
        existing = _existing_rider(policy)
        if existing and existing.get('document_hash'):
            raise PhinSafeIntegrityError(
                f'policy {policy_id} already has a permanent PhinSafe settlement',
                status=409,
            )
        coverage_cents, annual_cents, savings_cents = _policy_money(policy)
        benefit = _benefit_cents(coverage_cents)
        premium = annual_cents // BENEFIT_DENOMINATOR
        savings = savings_cents // BENEFIT_DENOMINATOR
        if premium < savings:
            raise PhinSafeIntegrityError(f'policy {policy_id} rider savings exceed rider premium')
        slices.append({
            'policy_id': policy_id,
            'parent_coverage': cents_to_dollars(coverage_cents),
            'parent_coverage_cents': coverage_cents,
            'benefit': cents_to_dollars(benefit),
            'benefit_cents': benefit,
            'annual_premium': cents_to_dollars(premium),
            'annual_premium_cents': premium,
            'savings_premium': cents_to_dollars(savings),
            'savings_premium_cents': savings,
            'risk_premium': cents_to_dollars(premium - savings),
            'risk_premium_cents': premium - savings,
        })
        benefit_total += benefit
        annual_total += premium
        savings_total += savings
        policy_ids.append(policy_id)

    # One fifth of each policy, summed. Never one fifth of a blended face
    # that could hide a rounding difference across policies.
    if benefit_total != sum(slice_['benefit_cents'] for slice_ in slices):
        raise PhinSafeIntegrityError('per-policy benefits do not sum', status=409)
    if any(slice_['benefit_cents'] * BENEFIT_DENOMINATOR > slice_['parent_coverage_cents'] for slice_ in slices):
        raise PhinSafeIntegrityError('a policy benefit exceeds one fifth of its face', status=409)

    rider_core = {
        'product_id': PRODUCT_ID,
        'customer_id': customer_id,
        'policy_ids': sorted(policy_ids),
        'community_id': community_id,
        'community_max_joining_age': cap,
        'parent_age_at_join': parent_age,
        'join_date': joined.isoformat(),
        'coverage_starts': coverage_starts.isoformat(),
        'waiting_years': WAITING_YEARS,
        'settlement': SETTLEMENT,
        'benefit_fraction': f'{BENEFIT_NUMERATOR}/{BENEFIT_DENOMINATOR}',
        'first_pregnancy_start': pregnancy.isoformat() if pregnancy else None,
        'benefit_cents': benefit_total,
        'annual_premium_cents': annual_total,
        'savings_premium_cents': savings_total,
        'book_hash': book_hash,
        'simulation_id': book.get('simulation_id'),
        'slices': slices,
    }
    doc_hash = document_hash(rider_core)
    rider_id = _entry_id('PHINSAFE', f'{customer_id}|{doc_hash}')
    status = 'in_force' if pregnancy else 'waiting'
    rider = {
        **rider_core,
        'rider_id': rider_id,
        'document_hash': doc_hash,
        'status': status,
        'benefit': cents_to_dollars(benefit_total),
        'annual_premium': cents_to_dollars(annual_total),
        'savings_premium': cents_to_dollars(savings_total),
        'risk_premium': cents_to_dollars(annual_total - savings_total),
        'monthly_premium': cents_to_dollars(installment_cents(annual_total, 0)),
        'monthly_savings_premium': cents_to_dollars(installment_cents(savings_total, 0)),
        'primary_policy_id': sorted(policy_ids)[0],
        'open_claims_cents': 0,
        'open_claim_ids': [],
    }
    patches = {}
    for policy, slice_ in zip(policies, slices):
        policy_id = slice_['policy_id']
        riders = policy.get('riders')
        if isinstance(riders, str):
            try:
                riders = json.loads(riders or '{}')
            except json.JSONDecodeError:
                riders = {}
        riders = dict(riders) if isinstance(riders, dict) else {}
        riders[PRODUCT_ID] = {
            'rider_id': rider_id,
            'product_id': PRODUCT_ID,
            'document_hash': doc_hash,
            'book_hash': book_hash,
            'settlement': SETTLEMENT,
            'status': status,
            'benefit': slice_['benefit'],
            'benefit_cents': slice_['benefit_cents'],
            'total_benefit': cents_to_dollars(benefit_total),
            'total_benefit_cents': benefit_total,
            'annual_premium': slice_['annual_premium'],
            'annual_premium_cents': slice_['annual_premium_cents'],
            'total_annual_premium': cents_to_dollars(annual_total),
            'total_annual_premium_cents': annual_total,
            'savings_premium': slice_['savings_premium'],
            'savings_premium_cents': slice_['savings_premium_cents'],
            'total_savings_premium': cents_to_dollars(savings_total),
            'total_savings_premium_cents': savings_total,
            'monthly_premium': cents_to_dollars(installment_cents(slice_['annual_premium_cents'], 0)),
            'monthly_savings_premium': cents_to_dollars(installment_cents(slice_['savings_premium_cents'], 0)),
            'join_date': joined.isoformat(),
            'coverage_starts': coverage_starts.isoformat(),
            'waiting_years': WAITING_YEARS,
            'community_id': community_id,
            'simulation_id': book.get('simulation_id'),
            'customer_id': customer_id,
            'primary_policy_id': sorted(policy_ids)[0],
            'policy_ids': sorted(policy_ids),
            'first_pregnancy_start': pregnancy.isoformat() if pregnancy else None,
            'open_claims_cents': 0,
            'open_claim_ids': [],
        }
        billing = _billing_dict(policy)
        billing['phinsafe'] = {
            'rider_id': rider_id,
            'annual_premium': slice_['annual_premium'],
            'monthly_premium': riders[PRODUCT_ID]['monthly_premium'],
            'monthly_savings_premium': riders[PRODUCT_ID]['monthly_savings_premium'],
            'separate_from_parent_premium': True,
        }
        patches[policy_id] = {'riders': riders, 'billing': billing}

    bill = build_installment(rider, year=joined.year, month=joined.month)
    return {
        'rider': rider,
        'policy_patches': patches,
        'bill': bill,
        'ledger': {
            'event_type': RIDER_EVENT,
            'entry_id': _entry_id('PHINSAFE-RIDER', f'{rider_id}|{book_hash}'),
            'entity_id': rider_id,
            'customer_id': customer_id,
            'amount': rider['annual_premium'],
            'payload': {
                'product_id': PRODUCT_ID,
                'rider_id': rider_id,
                'document_hash': doc_hash,
                'book_hash': book_hash,
                'simulation_id': book.get('simulation_id'),
                'customer_id': customer_id,
                'policy_ids': sorted(policy_ids),
                'community_id': community_id,
                'parent_age_at_join': parent_age,
                'benefit': rider['benefit'],
                'annual_premium': rider['annual_premium'],
                'savings_premium': rider['savings_premium'],
                'join_date': joined.isoformat(),
                'coverage_starts': coverage_starts.isoformat(),
                'waiting_years': WAITING_YEARS,
                'settlement': SETTLEMENT,
                'status': status,
            },
        },
    }


def anchor_rider(ledger: Any, bound: Mapping[str, Any], *, actor: str) -> Dict[str, Any]:
    spec = bound.get('ledger') or {}
    try:
        entry = ledger.append_event(
            event_type=spec.get('event_type') or RIDER_EVENT,
            entity_type=LEDGER_ENTITY,
            entity_id=str(spec.get('entity_id') or ''),
            customer_id=spec.get('customer_id'),
            actor=actor or 'actuary',
            amount=float(spec.get('amount') or 0),
            status='pending' if spec.get('event_type') == CLAIM_EVENT else 'bound',
            source_system=SOURCE_SYSTEM,
            entry_id=str(spec.get('entry_id') or ''),
            payload=dict(spec.get('payload') or {}),
        )
    except Exception as exc:
        raise PhinSafeIntegrityError(
            f'ledger refused the PhinSafe settlement: {exc}',
            status=503,
        ) from exc
    return {
        'entry_id': str(entry.get('id') or spec.get('entry_id')),
        'entry_hash': str(entry.get('entry_hash') or ''),
        'sequence_no': entry.get('sequence_no'),
        'event_type': str(spec.get('event_type') or RIDER_EVENT),
    }


def rider_from_policy(policy: Mapping[str, Any]) -> Dict[str, Any]:
    """Full-rider view stored on one parent policy."""
    existing = _existing_rider(policy)
    if not existing or not existing.get('rider_id'):
        raise PhinSafeIntegrityError('this policy has no PhinSafe rider')
    benefit_cents = int(existing.get('total_benefit_cents') or existing.get('benefit_cents') or 0)
    annual_cents = _rider_annual_cents(existing)
    savings_cents = _rider_savings_cents(existing)
    return {
        'rider_id': existing.get('rider_id'),
        'document_hash': existing.get('document_hash'),
        'coverage_starts': existing.get('coverage_starts'),
        'join_date': existing.get('join_date'),
        'benefit_cents': benefit_cents,
        'benefit': existing.get('total_benefit') or existing.get('benefit'),
        'open_claims_cents': int(existing.get('open_claims_cents') or 0),
        'open_claim_ids': [str(item) for item in (existing.get('open_claim_ids') or [])],
        'first_pregnancy_start': existing.get('first_pregnancy_start'),
        'primary_policy_id': existing.get('primary_policy_id') or policy.get('id'),
        'customer_id': existing.get('customer_id') or policy.get('customer_id'),
        'annual_premium_cents': annual_cents,
        'savings_premium_cents': savings_cents,
        'annual_premium': cents_to_dollars(annual_cents),
        'savings_premium': cents_to_dollars(savings_cents),
        'policy_ids': list(existing.get('policy_ids') or []),
        'status': existing.get('status'),
    }


def savings_fraction(rider: Mapping[str, Any]) -> float:
    annual = _rider_annual_cents(rider)
    savings = _rider_savings_cents(rider)
    if annual <= 0 or savings <= 0:
        return 0.0
    return savings / annual


def open_claim(
    rider: Mapping[str, Any],
    *,
    amount: Any,
    incident_date: Any,
    pregnancy_start: Any,
) -> Dict[str, Any]:
    """Admit a child-catastrophe claim onto the claims book. Does not pay it."""
    incident = _parse_date(incident_date, 'incident_date')
    pregnancy = _parse_date(pregnancy_start, 'pregnancy_start')
    starts = _parse_date(rider.get('coverage_starts'), 'coverage_starts')
    if pregnancy < starts:
        raise PhinSafeIntegrityError('first pregnancy begins during the one-year waiting period')
    if incident < pregnancy:
        raise PhinSafeIntegrityError('the catastrophe date is before the first pregnancy')
    locked = rider.get('first_pregnancy_start')
    if locked and _parse_date(locked, 'first_pregnancy_start') != pregnancy:
        raise PhinSafeIntegrityError(
            'the first pregnancy date is already settled and cannot be replaced',
            status=409,
        )
    amount_cents = money_cents(amount)
    if amount_cents <= 0:
        raise PhinSafeIntegrityError('claim amount must be positive')
    benefit = int(rider.get('benefit_cents') or money_cents(rider.get('benefit') or 0))
    open_cents = int(rider.get('open_claims_cents') or 0)
    claim_core = {
        'rider_id': rider.get('rider_id'),
        'document_hash': rider.get('document_hash'),
        'amount_cents': amount_cents,
        'incident_date': incident.isoformat(),
        'pregnancy_start': pregnancy.isoformat(),
        'benefit_cents': benefit,
    }
    claim_id = _entry_id('CLM-PS', canonical_json(claim_core), limit=50)
    # A retried request carries the same claim id, so the benefit it already
    # reserved is not reserved a second time.
    open_claim_ids = [str(item) for item in (rider.get('open_claim_ids') or [])]
    if claim_id not in open_claim_ids:
        if open_cents + amount_cents > benefit:
            raise PhinSafeIntegrityError('claim exceeds the remaining PhinSafe benefit', status=409)
        open_cents += amount_cents
        open_claim_ids.append(claim_id)
    return {
        'claim': {
            'id': claim_id,
            'policy_id': rider.get('primary_policy_id'),
            'customer_id': rider.get('customer_id'),
            'type': PRODUCT_ID,
            'description': 'PhinSafe child catastrophe claim',
            'claimed_amount': cents_to_dollars(amount_cents),
            'status': 'pending',
            'incident_date': incident.isoformat(),
            'payment_destination': 'health_wallet',
            'rider_id': rider.get('rider_id'),
            'pregnancy_start': pregnancy.isoformat(),
            'document_hash': document_hash(claim_core),
        },
        'open_claims_cents': open_cents,
        'open_claim_ids': open_claim_ids,
        'first_pregnancy_start': pregnancy.isoformat(),
        'ledger': {
            'event_type': CLAIM_EVENT,
            'entry_id': _entry_id('PHINSAFE-CLAIM', claim_id),
            'entity_id': str(rider.get('rider_id') or ''),
            'customer_id': rider.get('customer_id'),
            'amount': cents_to_dollars(amount_cents),
            'payload': {
                'product_id': PRODUCT_ID,
                'claim_id': claim_id,
                'rider_id': rider.get('rider_id'),
                'rider_document_hash': rider.get('document_hash'),
                'claimed_amount': cents_to_dollars(amount_cents),
                'incident_date': incident.isoformat(),
                'pregnancy_start': pregnancy.isoformat(),
                'status': 'pending',
            },
        },
    }


def finalize_accepted_money_by_age(
    age_money: Mapping[int, Mapping[str, Any]],
    totals: Mapping[str, Any],
    accepted_count: int,
) -> Dict[str, Any]:
    """Publish the per-age accepted money ledger and prove it matches the book."""
    rows: List[Dict[str, Any]] = []
    for age in sorted(age_money):
        raw = age_money[age]
        row = {
            'age': int(age),
            'accepted': int(raw.get('accepted') or 0),
            'term_years': int(raw.get('term_years') or 0),
            'coverage': float(raw.get('coverage') or 0.0),
            'annual_premium': float(raw.get('annual_premium') or 0.0),
            'risk_premium': float(raw.get('risk_premium') or 0.0),
            'savings_premium': float(raw.get('savings_premium') or 0.0),
            'pv_mortality': float(raw.get('pv_mortality') or 0.0),
            'pv_disability': float(raw.get('pv_disability') or 0.0),
            'expected_claims_year1': float(raw.get('expected_claims_year1') or 0.0),
        }
        if row['accepted'] > 0:
            rows.append(row)
    summed_accepted = sum(row['accepted'] for row in rows)
    summed_coverage = sum(row['coverage'] for row in rows)
    summed_annual = sum(row['annual_premium'] for row in rows)
    summed_risk = sum(row['risk_premium'] for row in rows)
    summed_savings = sum(row['savings_premium'] for row in rows)

    def _close(left: float, right: float) -> bool:
        return abs(float(left) - float(right)) <= 0.02

    checks = {
        'accepted_matches_portfolio': summed_accepted == int(accepted_count),
        'coverage_matches_portfolio': _close(summed_coverage, totals.get('coverage') or 0),
        'annual_premium_matches_portfolio': _close(summed_annual, totals.get('annual_premium') or 0),
        'risk_premium_matches_portfolio': _close(summed_risk, totals.get('risk_premium') or 0),
        'savings_premium_matches_portfolio': _close(summed_savings, totals.get('savings_premium') or 0),
    }
    return {
        'rows': rows,
        'integrity': {
            'checks': checks,
            'all_checks_pass': all(checks.values()),
        },
    }
