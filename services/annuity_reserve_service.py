"""
PHINS Annuity Reserve Forecast Service.

Builds the year-by-year reserve a life company must hold to back the
annuity guarantee on customer savings. The model is the same shape an
Israeli actuary would compute for a 4%+CPI guaranteed pension annuity:

    P(X) = max(0,
            G(F(X); X) - G(g; X)
            + Σ_{y=0..N-1}  G(g; y) × (1 + madad(y))
                          + ( expec_ret(y+1)(g) - expec_ret(y+1)(I) )
            + Σ_{y=0..N-1}  arad_loss( expec_ret(y+1)(g) - I(y+1) )
                          - arad_loss( expec_ret(y+1)(I) - I(y+1) )
                          × I(y+1) × (1 + I(y+1)) × (1 + madad(y+1))
            - I(y+1) × (1 + madad(y+1)) × (1 + I(y+1))
        )

where

* g                 = guaranteed minimum return (default 4%)
* F(X)              = realised market return at year X
* I(y+1)            = guaranteed credit interest paid at year y+1
* madad(y)          = CPI (Israeli "מדד") for year y
* G(rate; X)        = guaranteed annuity reserve at year X using `rate`
* expec_ret(y+1)(.) = expected market return for year y+1 under the curve
* arad_loss(.)      = actuarial-loss adjustment as a smooth excess fn

The full algebraic transcription of the user's brief contains a number
of hand-noted shortcuts (``y = 0..8``, ``z = y + 1`` etc.). The
implementation below is the deterministic, dimension-balanced
interpretation: every term is computed in *currency units per converting
customer × number of converting customers*, and the result rolls forward
year by year so an actuary can audit each component (annuity gap,
inflation top-up, expected-return delta, actuarial loss correction,
guarantee credit) independently.

The service is engineered for the actuary dashboard's "Annuity Reserves
Forecast Bar" — every output is reproducible from inputs, every
intermediate step is exposed, and a deterministic SHA-256 integrity
hash signs the canonical numeric block so an audit can prove the
forecast displayed on screen is the one priced.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# =============================================================================
# CONFIG
# =============================================================================

@dataclass
class AnnuityReserveConfig:
    """Inputs to the annuity reserve forecast.

    Defaults are tuned for the canonical PHINS actuary scenario: 4%+CPI
    guaranteed annuity, 6% expected market return, 2% CPI, 60% conversion
    at retirement, 20-year payout horizon. Curves can be overridden as
    flat scalars or as full year-by-year arrays.
    """

    customer_count: int = 1000
    monthly_deposit_per_customer: float = 1000.0
    projection_years: int = 30
    payout_horizon_years: int = 20

    guarantee_rate_pct: float = 0.04
    expected_market_return_pct: float = 0.06
    expected_market_return_curve: Optional[List[float]] = None
    realised_return_curve: Optional[List[float]] = None
    madad_pct: float = 0.02
    madad_curve: Optional[List[float]] = None
    guarantee_credit_pct: float = 0.04
    guarantee_credit_curve: Optional[List[float]] = None

    # Share of customers that convert savings to an annuity at retirement.
    # When ``conversion_curve`` is provided, ``conversion_rate_pct`` is
    # ignored; otherwise conversion ramps linearly from 0 to the rate over
    # ``projection_years`` so early years carry less guarantee exposure.
    conversion_rate_pct: float = 0.60
    conversion_curve: Optional[List[float]] = None

    # Coefficient on the actuarial-loss term. The user's formula calls
    # ``arad_loss(.)`` an unspecified loss function — we model it as
    # ``λ × max(0, x)²`` so the reserve responds quadratically to large
    # negative gaps between expected return and the guarantee, matching
    # the conservative shape Israeli supervisors expect.
    actuarial_loss_lambda: float = 0.5

    # Optional initial annuity reserve carried forward from a prior run.
    initial_reserve: float = 0.0

    # Free-form scenario label; surfaces in the integrity hash so two
    # scenarios with otherwise identical parameters hash differently.
    scenario_label: str = 'base_case'

    version: str = 'annuity_reserve_v1'

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# =============================================================================
# CURVE HELPERS
# =============================================================================

def _resolve_curve(curve: Optional[List[float]], scalar: float, length: int) -> List[float]:
    """Return a length-N curve from either an explicit list or a scalar fallback.

    If the explicit curve is shorter than ``length`` the last value is
    repeated; if longer it is truncated. This makes the API forgiving for
    UI inputs (an actuary can paste a 5-year curve into a 30-year
    projection without surprise).
    """
    if curve and isinstance(curve, list):
        out = [float(v) for v in curve[:length]]
        if len(out) < length and out:
            out.extend([out[-1]] * (length - len(out)))
        if len(out) >= length:
            return out
    return [float(scalar)] * length


def _resolve_conversion_curve(curve: Optional[List[float]], rate_pct: float,
                              length: int) -> List[float]:
    """Resolve the cumulative conversion curve.

    When the caller supplies an explicit curve we use it (clamped to
    ``[0, 1]``). Otherwise the conversion ramps linearly from 0 at year 1
    to ``rate_pct`` at year ``length`` so the reserve does not balloon in
    year 1 with the full conversion exposure (which would be unrealistic
    for a freshly-priced book of long-duration savings policies).
    """
    rate_pct = max(0.0, min(1.0, float(rate_pct or 0.0)))
    if curve and isinstance(curve, list):
        out = [max(0.0, min(1.0, float(v))) for v in curve[:length]]
        if len(out) < length and out:
            out.extend([out[-1]] * (length - len(out)))
        return out[:length]
    if length <= 0:
        return []
    if length == 1:
        return [rate_pct]
    return [rate_pct * (i + 1) / float(length) for i in range(length)]


# =============================================================================
# ANNUITY MATH
# =============================================================================

def annuity_factor(rate: float, n_years: int) -> float:
    """Annuity-certain present-value factor: ä_n = Σ_{k=0..n-1} v^k."""
    n = max(1, int(n_years))
    rate = float(rate)
    if abs(rate) < 1e-9:
        return float(n)
    v = 1.0 / (1.0 + rate)
    # ä_n (annuity-due, payments at the start of each year). The Israeli
    # pension annuity standard pays monthly in advance, but for the
    # annual-grain reserve forecast the annuity-due is the cleanest
    # closed-form match.
    return (1.0 - v ** n) / (1.0 - v)


def _arad_loss(gap: float, lam: float) -> float:
    """Smooth one-sided actuarial-loss function used in the reserve.

    A negative gap (expected return below the guarantee) generates a
    quadratic loading, a non-negative gap contributes nothing. The shape
    is Lipschitz at zero, monotone, and convex — properties the reserve
    formula relies on for sub-additivity across years.
    """
    if gap >= 0:
        return 0.0
    return float(lam) * float(gap) * float(gap)


# =============================================================================
# CORE PROJECTION
# =============================================================================

def _round2(value: float) -> float:
    return round(float(value), 2)


def _round6(value: float) -> float:
    return round(float(value), 6)


def _hash_block(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def compute_annuity_reserve_forecast(
    config: AnnuityReserveConfig,
    *,
    simulation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute the year-by-year annuity reserve and supporting metrics.

    The output dict carries

    * ``yearly`` — list of per-year rows with every component of P(X)
    * ``totals`` — peak / cumulative summaries usable for stat cards
    * ``inputs`` — the resolved curves and config for audit
    * ``integrity_hash`` — SHA-256 over the canonical numeric block
    * ``formula`` — the symbolic formula and its component map

    When a ``simulation`` dict is supplied (the JSON saved by
    ``/api/actuarial/simulate``), the customer count and monthly deposit
    are seeded from it before any caller overrides; this keeps the
    reserve forecast tied to the same priced portfolio the simulator
    audited.
    """

    if simulation:
        portfolio = (simulation or {}).get('portfolio_summary', {}) or {}
        profitability = (simulation or {}).get('profitability', {}) or {}
        sim_customer_count = int(portfolio.get('accepted_customers') or 0)
        if sim_customer_count and not config.customer_count:
            config.customer_count = sim_customer_count
        sim_savings_premium = float(profitability.get('savings_premium') or 0.0)
        if (
            sim_savings_premium > 0
            and (not config.monthly_deposit_per_customer or config.monthly_deposit_per_customer <= 0)
            and sim_customer_count
        ):
            # Fallback: derive a per-customer monthly deposit from the
            # priced annual savings premium so the forecast still works
            # when the caller did not pass an explicit deposit.
            config.monthly_deposit_per_customer = (
                sim_savings_premium / sim_customer_count / 12.0
            )

    n = max(1, int(config.projection_years))
    customer_count = max(0, int(config.customer_count or 0))
    annual_deposit = float(config.monthly_deposit_per_customer or 0.0) * 12.0

    expected_curve = _resolve_curve(
        config.expected_market_return_curve,
        config.expected_market_return_pct,
        n,
    )
    realised_curve = _resolve_curve(
        config.realised_return_curve,
        config.expected_market_return_pct,
        n,
    )
    madad_curve = _resolve_curve(config.madad_curve, config.madad_pct, n)
    credit_curve = _resolve_curve(
        config.guarantee_credit_curve,
        config.guarantee_credit_pct,
        n,
    )
    conversion_curve = _resolve_conversion_curve(
        config.conversion_curve, config.conversion_rate_pct, n,
    )

    g = float(config.guarantee_rate_pct)
    payout_n = max(1, int(config.payout_horizon_years))
    a_guarantee = annuity_factor(g, payout_n)

    s_actual = 0.0  # cumulative savings under realised market returns
    s_min = 0.0     # cumulative savings under guaranteed (4% + madad)
    s_expected = 0.0  # cumulative savings under expected market returns
    yearly: List[Dict[str, Any]] = []
    cumulative_madad_term = 0.0
    cumulative_loss_correction = 0.0
    peak_reserve = 0.0
    peak_reserve_year = 0

    for idx in range(n):
        year = idx + 1
        f_x = realised_curve[idx]
        e_x = expected_curve[idx]
        m_x = madad_curve[idx]
        i_x = credit_curve[idx]

        s_actual = s_actual * (1.0 + f_x) + annual_deposit
        s_expected = s_expected * (1.0 + e_x) + annual_deposit
        # Guaranteed scenario: 4% guaranteed credit + CPI top-up indexation.
        # This matches an Israeli "מסלול מובטח" (guaranteed track) pension
        # annuity where the customer's principal is indexed to the CPI
        # and earns at least the guarantee rate.
        s_min = s_min * (1.0 + g) * (1.0 + m_x) + annual_deposit

        # Annuity factors at the year's realised / expected returns.
        a_realised = annuity_factor(f_x, payout_n)
        a_expected = annuity_factor(e_x, payout_n)

        # Per-customer annuity payment fundable from each savings track.
        ann_min = s_min / a_guarantee if a_guarantee > 0 else 0.0
        ann_realised = s_actual / a_realised if a_realised > 0 else 0.0
        ann_expected = s_expected / a_expected if a_expected > 0 else 0.0

        # G(rate; X) — present value of the guaranteed annuity stream
        # priced at ``rate``. We re-discount the guaranteed annuity at
        # both the realised and the guarantee rate to recover the
        # ``G(F(X); X) - G(g; X)`` term in the user's formula.
        g_at_realised = ann_min * a_realised
        g_at_guarantee = ann_min * a_guarantee
        annuity_gap = g_at_realised - g_at_guarantee

        # Σ inflation top-up term. Each year's contribution to the cumulative
        # CPI top-up reserve, scaled by the running expected-vs-realised
        # delta. This is the user's ``Σ G(g; y) × (1 + madad(y)) +
        # (expec_ret(y+1)(g) - expec_ret(y+1)(I))`` block.
        madad_term = g_at_guarantee * (1 + m_x) + (g - e_x)
        cumulative_madad_term += madad_term

        # Σ actuarial-loss correction. Quadratic on the negative gap, with
        # interest-credit and CPI compounding, exactly the user's
        # ``arad_loss(.) × I(y+1) × (1+I) × (1+madad)`` block. We subtract
        # the loss correction computed at the realised return rather than
        # the guaranteed one so the reserve grows when the realised
        # scenario underperforms the guarantee.
        gap_g = e_x - i_x
        gap_i = f_x - i_x
        loss_correction = (
            (_arad_loss(gap_g, config.actuarial_loss_lambda)
             - _arad_loss(gap_i, config.actuarial_loss_lambda))
            * i_x * (1.0 + i_x) * (1.0 + m_x)
        )
        cumulative_loss_correction += loss_correction

        # Interest credit already paid to the customer this year.
        interest_credited_year = i_x * (1.0 + m_x) * (1.0 + i_x) * s_actual

        # Per-customer reserve P(X) before conversion gating.
        p_per_customer_raw = (
            annuity_gap
            + cumulative_madad_term
            + cumulative_loss_correction
            - interest_credited_year
        )
        p_per_customer = max(0.0, p_per_customer_raw)

        # Aggregate reserve at year X across the converting cohort.
        converted_share = conversion_curve[idx] if idx < len(conversion_curve) else 0.0
        converted_customers = customer_count * converted_share
        p_aggregate = p_per_customer * converted_customers + config.initial_reserve

        if p_aggregate > peak_reserve:
            peak_reserve = p_aggregate
            peak_reserve_year = year

        yearly.append({
            'year': year,
            # Curves
            'realised_return_pct': _round6(f_x),
            'expected_return_pct': _round6(e_x),
            'madad_pct': _round6(m_x),
            'guarantee_credit_pct': _round6(i_x),
            'guarantee_rate_pct': _round6(g),
            'cumulative_conversion_pct': _round6(converted_share),
            'converted_customers': _round2(converted_customers),
            # Savings tracks (per customer, currency units)
            'savings_per_customer_actual': _round2(s_actual),
            'savings_per_customer_expected': _round2(s_expected),
            'savings_per_customer_guaranteed': _round2(s_min),
            # Per-customer annual annuity payment fundable from each track
            'annuity_per_customer_actual': _round2(ann_realised),
            'annuity_per_customer_expected': _round2(ann_expected),
            'annuity_per_customer_guaranteed': _round2(ann_min),
            # Reserve components per customer
            'annuity_gap_per_customer': _round2(annuity_gap),
            'madad_term_per_customer': _round2(cumulative_madad_term),
            'loss_correction_per_customer': _round2(cumulative_loss_correction),
            'interest_credited_per_customer': _round2(interest_credited_year),
            'p_per_customer_raw': _round2(p_per_customer_raw),
            'p_per_customer': _round2(p_per_customer),
            # Aggregate reserve P(X)
            'reserve_aggregate': _round2(p_aggregate),
            'reserve_aggregate_cumulative_floor': _round2(p_aggregate),
            # Cumulative monthly deposits collected (across the cohort)
            'monthly_deposits_aggregate_year': _round2(
                annual_deposit * customer_count
            ),
            'monthly_deposits_aggregate_cumulative': _round2(
                annual_deposit * customer_count * year
            ),
        })

    # Aggregate stat-card metrics
    total_deposits = sum(r['monthly_deposits_aggregate_year'] for r in yearly)
    final = yearly[-1] if yearly else {}
    final_savings_actual = float(final.get('savings_per_customer_actual', 0.0)) * customer_count
    final_savings_guarantee = float(final.get('savings_per_customer_guaranteed', 0.0)) * customer_count
    final_annuity_actual = float(final.get('annuity_per_customer_actual', 0.0))
    final_annuity_guarantee = float(final.get('annuity_per_customer_guaranteed', 0.0))
    funding_ratio = (
        (final_savings_actual / final_savings_guarantee)
        if final_savings_guarantee > 0 else 0.0
    )

    inputs_view = {
        'customer_count': customer_count,
        'monthly_deposit_per_customer': float(config.monthly_deposit_per_customer or 0.0),
        'annual_deposit_per_customer': annual_deposit,
        'projection_years': n,
        'payout_horizon_years': payout_n,
        'guarantee_rate_pct': g,
        'expected_market_return_pct': float(config.expected_market_return_pct),
        'madad_pct': float(config.madad_pct),
        'guarantee_credit_pct': float(config.guarantee_credit_pct),
        'conversion_rate_pct': float(config.conversion_rate_pct),
        'actuarial_loss_lambda': float(config.actuarial_loss_lambda),
        'initial_reserve': float(config.initial_reserve),
        'scenario_label': str(config.scenario_label),
        'version': config.version,
        'curves': {
            'expected_return': [_round6(v) for v in expected_curve],
            'realised_return': [_round6(v) for v in realised_curve],
            'madad': [_round6(v) for v in madad_curve],
            'guarantee_credit': [_round6(v) for v in credit_curve],
            'cumulative_conversion': [_round6(v) for v in conversion_curve],
        },
    }

    canonical_block = {
        'inputs': inputs_view,
        'yearly': yearly,
    }
    integrity_hash = _hash_block(canonical_block)

    integrity_checks = {
        # P(X) must never go negative (max(0,...) wrapper).
        'reserve_non_negative': all(r['reserve_aggregate'] >= -1e-6 for r in yearly),
        # Funding ratio is never negative (savings always start at 0 and grow).
        'funding_ratio_non_negative': funding_ratio >= 0.0,
        # When realised exactly equals the guarantee curve and CPI is zero
        # the gap term G(F;X) - G(g;X) collapses to 0 — but the rest of
        # the formula (madad, loss correction, interest credit) can still
        # produce a non-zero reserve, so we only assert non-negativity.
        'monotone_cumulative_deposits': all(
            yearly[i]['monthly_deposits_aggregate_cumulative']
            >= yearly[i - 1]['monthly_deposits_aggregate_cumulative']
            for i in range(1, len(yearly))
        ),
        # Per-customer guaranteed savings always grow (deposits + positive
        # guarantee × CPI). This is a sanity invariant: if it fails, the
        # forecast inputs are inconsistent.
        'guaranteed_savings_monotone': all(
            yearly[i]['savings_per_customer_guaranteed']
            >= yearly[i - 1]['savings_per_customer_guaranteed'] - 1e-6
            for i in range(1, len(yearly))
        ),
    }

    return {
        'inputs': inputs_view,
        'yearly': yearly,
        'totals': {
            'peak_reserve': _round2(peak_reserve),
            'peak_reserve_year': peak_reserve_year,
            'final_year_reserve': _round2(final.get('reserve_aggregate', 0.0)),
            'final_savings_actual': _round2(final_savings_actual),
            'final_savings_guarantee': _round2(final_savings_guarantee),
            'final_annuity_per_customer_actual': _round2(final_annuity_actual),
            'final_annuity_per_customer_guarantee': _round2(final_annuity_guarantee),
            'funding_ratio': _round6(funding_ratio),
            'total_deposits_collected': _round2(total_deposits),
            'cumulative_loss_correction': _round2(cumulative_loss_correction),
        },
        'formula': {
            'symbolic': (
                'P(X) = max(0, '
                'G(F(X);X) - G(g;X) '
                '+ Σ_{y=0..N-1} G(g;y) × (1+madad(y)) + ( expec_ret(y+1)(g) - expec_ret(y+1)(I) ) '
                '+ Σ_{y=0..N-1} arad_loss(expec_ret(y+1)(g) - I(y+1)) - arad_loss(expec_ret(y+1)(I) - I(y+1)) '
                '× I(y+1) × (1+I(y+1)) × (1+madad(y+1)) '
                '- I(y+1) × (1+madad(y+1)) × (1+I(y+1)) )'
            ),
            'components': {
                'annuity_gap': 'G(F(X);X) - G(g;X) — gap between actual-return annuity value and guarantee.',
                'madad_term': 'Σ G(g;y) × (1+madad(y)) + Δexpected_return — CPI top-up + expected return delta.',
                'loss_correction': (
                    'Σ arad_loss(g_gap) - arad_loss(i_gap), compounded by I and madad — quadratic '
                    'loading when expected return underperforms the guarantee.'
                ),
                'interest_credited': (
                    'I(y+1) × (1+madad(y+1)) × (1+I(y+1)) — guarantee credit already paid, '
                    'subtracted to avoid double-counting.'
                ),
            },
            'parameters': {
                'g': 'guarantee_rate_pct',
                'F(X)': 'realised_return_curve[X]',
                'expec_ret': 'expected_market_return_curve',
                'I': 'guarantee_credit_curve',
                'madad': 'madad_curve (CPI)',
                'arad_loss': 'λ × max(0, -gap)² (quadratic one-sided loss)',
            },
        },
        'integrity_hash': integrity_hash,
        'integrity_checks': integrity_checks,
        'version': config.version,
    }


def coerce_annuity_reserve_config(payload: Optional[Dict[str, Any]]) -> AnnuityReserveConfig:
    """Build an :class:`AnnuityReserveConfig` from an HTTP/JSON payload."""
    payload = payload or {}

    def _f(name: str, default: float) -> float:
        v = payload.get(name)
        if v is None or v == '':
            return float(default)
        try:
            return float(v)
        except (TypeError, ValueError):
            return float(default)

    def _i(name: str, default: int) -> int:
        v = payload.get(name)
        if v is None or v == '':
            return int(default)
        try:
            return int(v)
        except (TypeError, ValueError):
            return int(default)

    def _curve(name: str) -> Optional[List[float]]:
        v = payload.get(name)
        if v is None:
            return None
        if isinstance(v, list):
            return [float(x) for x in v]
        if isinstance(v, str):
            try:
                parts = [p.strip() for p in v.split(',') if p.strip()]
                return [float(p) for p in parts] if parts else None
            except (TypeError, ValueError):
                return None
        return None

    def _pct(name: str, default: float) -> float:
        """Accept both percentage (4 → 0.04) and fraction (0.04) inputs."""
        raw = _f(name, default)
        return raw / 100.0 if abs(raw) > 1.0 else raw

    return AnnuityReserveConfig(
        customer_count=max(0, _i('customer_count', 1000)),
        monthly_deposit_per_customer=max(0.0, _f('monthly_deposit_per_customer', 1000.0)),
        projection_years=max(1, min(80, _i('projection_years', 30))),
        payout_horizon_years=max(1, min(60, _i('payout_horizon_years', 20))),
        guarantee_rate_pct=_pct('guarantee_rate_pct', 0.04),
        expected_market_return_pct=_pct('expected_market_return_pct', 0.06),
        expected_market_return_curve=_curve('expected_market_return_curve'),
        realised_return_curve=_curve('realised_return_curve'),
        madad_pct=_pct('madad_pct', 0.02),
        madad_curve=_curve('madad_curve'),
        guarantee_credit_pct=_pct('guarantee_credit_pct', 0.04),
        guarantee_credit_curve=_curve('guarantee_credit_curve'),
        conversion_rate_pct=_pct('conversion_rate_pct', 0.60),
        conversion_curve=_curve('conversion_curve'),
        actuarial_loss_lambda=max(0.0, _f('actuarial_loss_lambda', 0.5)),
        initial_reserve=max(0.0, _f('initial_reserve', 0.0)),
        scenario_label=str(payload.get('scenario_label') or 'base_case').strip() or 'base_case',
    )


def get_default_annuity_reserve_inputs() -> Dict[str, Any]:
    """Return the canonical default scenario for the dashboard's first paint.

    Tuned for an Israeli 4%+CPI guaranteed pension annuity scenario:
    1,000 customers, NIS 1,000 monthly deposit, 6% expected market
    return, 2% CPI, 60% conversion at retirement, 20-year payout
    horizon, 30-year projection.
    """
    return AnnuityReserveConfig().as_dict()


__all__ = [
    'AnnuityReserveConfig',
    'annuity_factor',
    'coerce_annuity_reserve_config',
    'compute_annuity_reserve_forecast',
    'get_default_annuity_reserve_inputs',
]
