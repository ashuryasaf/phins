"""Cent-exact identities for the Reserves & IFRS 17 waterfall columns.

IBNR, IFRS 17 BEL, RA, CSM Δ, CSM, Savings Δ and Savings Closing are the
columns on the actuary dashboard. Each one has to be recomputable from
the published row, and the claim path has to be the pricing kernel's
expected cash flows rather than a level annuity.
"""

from services.actuarial_service import (
    ReserveCalculator,
    SimulationParams,
    _coerce_reserve_config,
    _money,
    get_portfolio_simulator,
)
from services.pricing_kernel import (
    ClaimModel,
    PricingConfig,
    PricingCustomer,
    SavingsFormula,
    get_product,
    price_policy,
    table_set_from_store,
)
from services.actuarial_service import get_actuarial_store


def _assert_row_identities(proj, cfg):
    rate = proj['discount_rate']
    integrity = proj['data_integrity']
    for flag in (
        'bel_rollforward_holds',
        'bel_interest_equals_locked_in_rate',
        'bel_terminal_rounding_within_dollar',
        'ra_equals_pct_of_bel',
        'ibnr_equals_pct_of_claims',
        'opening_fulfilment_identity_holds',
        'csm_net_change_equals_accretion_minus_release',
        'csm_per_year_continuity_holds',
        'csm_sum_reconciles_to_opening',
        'savings_net_change_rolls_forward',
        'savings_accumulation_identity_holds',
    ):
        assert integrity[flag] is True, flag

    ob = proj['opening_balances']
    assert abs(
        (ob['csm'] - ob['loss_component'])
        - (ob['pv_insurance_premiums'] - ob['bel'] - ob['risk_adjustment'])
    ) < 0.001

    prev_csm = ob['csm']
    prev_sav = ob['savings_fund']
    prev_reserve = ob['reserve']
    for row in proj['yearly_projection']:
        ifr = row['ifrs17']
        sf = row['savings_fund']
        assert row['ibnr_provision'] == _money(row['in_force_expected_claims'] * cfg.ibnr_pct)
        assert ifr['bel_interest'] == _money(ifr['bel_opening'] * rate)
        assert ifr['bel_balance'] == _money(
            ifr['bel_opening'] + ifr['bel_interest']
            - row['in_force_expected_claims'] - ifr['bel_rounding']
        )
        assert abs(ifr['bel_rounding']) < 1.0
        assert ifr['risk_adjustment'] == _money(ifr['bel_balance'] * cfg.risk_adjustment_pct)
        assert ifr['csm_net_change'] == _money(ifr['csm_accretion'] - ifr['csm_release'])
        assert ifr['csm_balance'] == _money(prev_csm + ifr['csm_net_change'])
        assert sf['net_change'] == _money(
            sf['contribution'] + sf['yield'] - sf['management_fee_income']
        )
        assert sf['closing_balance'] == _money(prev_sav + sf['net_change'])
        assert sf['closing_balance'] == _money(
            sf['opening_balance'] + sf['contribution'] + sf['yield'] - sf['management_fee_income']
        )
        assert row['closing_reserve'] == _money(prev_reserve + row['reserve_contribution'])
        prev_csm = ifr['csm_balance']
        prev_sav = sf['closing_balance']
        prev_reserve = row['closing_reserve']

    rec = proj['csm_reconciliation']
    recon = (
        rec['opening_csm']
        + rec['totals']['sum_of_accretion']
        - rec['totals']['sum_of_releases']
    )
    assert abs(recon - rec['totals']['closing_csm']) < 0.001
    for flag, ok in rec['data_integrity'].items():
        assert ok is True, flag


def _synthetic_book():
    return {
        'simulation_id': 'SIM-IDENTITY',
        'portfolio_summary': {'total_annual_premium': 200000.0},
        'risk_metrics': {
            'annual_expected_claims': 40000.0,
            'avg_term_years': 5,
            'total_expected_claims': 180000.0,
            'expected_claims_year1': 30000.0,
            'expected_claims_by_year': [30000.0, 34000.0, 38000.0, 42000.0, 47000.0],
            'insurance_premium_by_year': [160000.0] * 5,
            'savings_premium_by_year': [40000.0] * 5,
        },
        'profitability': {
            'net_profit': 90000.0,
            'risk_premium': 50000.0,
            'savings_premium': 40000.0,
            'gross_premium': 200000.0,
        },
        'pricing_kernel': {'discount_rate': 0.035},
    }


def test_kernel_cashflow_vector_discounts_back_to_the_claim_pv():
    store = get_actuarial_store()
    tables = table_set_from_store(store)
    product = get_product('phins_pure_risk_adjustable')
    config = PricingConfig(
        expense_loading_pct=0.15,
        profit_margin_pct=0.10,
        discount_rate=0.035,
        savings_rate=0.0,
        savings_formula=SavingsFormula.RISK_PREMIUM_MARKUP,
        claim_model=ClaimModel.MUTUALLY_EXCLUSIVE,
    )
    priced = price_policy(
        PricingCustomer(age=40, coverage=250000, term_years=12, adl_level=5),
        product, tables, config,
    )
    rate = 0.035
    pv = sum(
        cf / ((1.0 + rate) ** year)
        for year, cf in enumerate(priced.expected_claims_by_year, start=1)
    )
    assert abs(pv - priced.pv_total_risk_claims) < 0.02
    assert abs(priced.expected_claims_by_year[0] - priced.expected_claims_year1) < 0.02


def test_dashboard_columns_reconcile_to_the_cent_for_both_csm_patterns():
    sim = _synthetic_book()
    for pattern in ('straight_line', 'coverage_units'):
        cfg = _coerce_reserve_config({
            'projection_years': 5,
            'csm_release_pattern': pattern,
            'ibnr_pct': 0.12,
            'risk_adjustment_pct': 0.06,
            'savings_yield_pct': 0.045,
            'management_fee_pct_of_aum': 0.01,
            'savings_allocation_pct': 0.05,
            'initial_savings_fund_balance': 500,
            'dividends_pct': 0.30,
            'tax_pct': 0.23,
            'reserve_contribution_pct': 0.40,
        })
        proj = ReserveCalculator().project(sim, cfg)
        assert proj['ifrs17_methodology']['claims_cashflow_basis'] == 'kernel_expected_cash_flows'
        assert proj['opening_balances']['csm'] > 0
        _assert_row_identities(proj, cfg)
        # Full runoff: BEL and CSM are both exhausted, IBNR is 12% of claims.
        last = proj['yearly_projection'][-1]
        assert last['ifrs17']['bel_balance'] == 0.0
        assert last['ifrs17']['csm_balance'] == 0.0
        assert last['ibnr_provision'] == _money(last['in_force_expected_claims'] * 0.12)
        # Claims follow the supplied incidence curve, not a level annuity.
        claims = [row['in_force_expected_claims'] for row in proj['yearly_projection']]
        assert claims[0] < claims[-1]


def test_short_projection_keeps_the_unexpired_bel():
    cfg = _coerce_reserve_config({
        'projection_years': 2,
        'csm_release_pattern': 'straight_line',
        'initial_savings_fund_balance': 0,
    })
    proj = ReserveCalculator().project(_synthetic_book(), cfg)
    _assert_row_identities(proj, cfg)
    assert proj['yearly_projection'][-1]['ifrs17']['bel_balance'] > 0
    assert proj['yearly_projection'][-1]['ifrs17']['bel_rounding'] == 0.0


def test_portfolio_year1_claims_match_the_kernel_and_feed_ibnr():
    sim = get_portfolio_simulator().generate_portfolio(SimulationParams(
        customer_count=80,
        age_min=30, age_max=55, age_mean=42.0, age_std=6.0,
        coverage_min=100000, coverage_max=400000, coverage_median=200000,
        policy_term_mode='fixed', policy_term_fixed=8,
        savings_rate=0.4,
    ))
    cfg = _coerce_reserve_config({
        'projection_years': 8,
        'ibnr_pct': 0.10,
        'risk_adjustment_pct': 0.06,
        'csm_release_pattern': 'coverage_units',
        'savings_yield_pct': 0.045,
        'management_fee_pct_of_aum': 0.01,
    })
    proj = ReserveCalculator().project(sim, cfg)
    _assert_row_identities(proj, cfg)
    accepted = sim['portfolio_summary']['accepted_customers']
    y1 = proj['yearly_projection'][0]['in_force_expected_claims']
    kernel_y1 = sim['risk_metrics']['expected_claims_year1']
    assert abs(y1 - kernel_y1) <= 0.01 * accepted + 0.02
    assert proj['yearly_projection'][0]['ibnr_provision'] == _money(y1 * 0.10)
    # Ageing book: expected claims rise. A level annuity would not.
    claims = [row['in_force_expected_claims'] for row in proj['yearly_projection']]
    assert claims[-1] > claims[0]
    assert proj['yearly_projection'][-1]['ifrs17']['bel_balance'] == 0.0
    # Present value of the published claim column equals the opening BEL
    # once the sub-dollar runoff plug is allowed for.
    rate = proj['discount_rate']
    pv = sum(
        row['in_force_expected_claims'] / ((1.0 + rate) ** row['year'])
        for row in proj['yearly_projection']
    )
    assert abs(pv - proj['opening_balances']['bel']) < 1.0


def test_legacy_snapshot_without_a_cashflow_vector_still_balances():
    sim = {
        'portfolio_summary': {'total_annual_premium': 100000.0},
        'risk_metrics': {
            'annual_expected_claims': 40000.0,
            'avg_term_years': 4,
            'total_expected_claims': 150000.0,
        },
        'profitability': {
            'net_profit': 20000.0,
            'risk_premium': 40000.0,
            'savings_premium': 0.0,
            'gross_premium': 100000.0,
        },
        'pricing_kernel': {'discount_rate': 0.035},
    }
    cfg = _coerce_reserve_config({'projection_years': 4, 'ibnr_pct': 0.10})
    proj = ReserveCalculator().project(sim, cfg)
    assert proj['ifrs17_methodology']['claims_cashflow_basis'] == 'level_annuity'
    _assert_row_identities(proj, cfg)
    assert proj['yearly_projection'][-1]['ifrs17']['bel_balance'] == 0.0
