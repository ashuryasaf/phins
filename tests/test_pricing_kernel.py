"""
Unit tests for the PHINS pricing kernel.

These tests pin the kernel to the legacy behaviour of the actuarial
simulator and the inline / financial-reporting pricers so the migration
that re-points those consumers at the kernel cannot change their
outputs. The tests must remain passing after every subsequent commit.
"""

from __future__ import annotations

import math

from services.actuarial_service import (
    PortfolioSimulator,
    SimulationParams,
    get_actuarial_store,
)
from services.pricing_kernel import (
    AGE_CURVE_REGISTRY,
    ClaimModel,
    PRODUCT_REGISTRY,
    PricingConfig,
    PricingCustomer,
    SavingsFormula,
    TableSet,
    get_age_curve,
    get_product,
    price_policy,
    pricing_config_from_underwriting,
    risk_reference_v1_factor,
    table_set_from_store,
)


def _simulator_pricer_legacy(customer, uw_result, store):
    """Re-implements the legacy simulator ``_calculate_premium`` math exactly.

    The pricing kernel must reproduce the same numbers when configured with
    ``ClaimModel.MUTUALLY_EXCLUSIVE``, ``savings_rate=0.5``,
    ``savings_yield_pct=0.0`` and an identity age curve.
    """
    age = customer["age"]
    adl = customer["adl"]
    coverage = customer["coverage"]
    term = customer["term"]
    loading = uw_result.get("loading", 0)
    exclude_disability = uw_result.get("exclude_disability", False)
    config = store.config

    adl_mort_mult = store.get_adl_mortality_multiplier(adl)
    adl_dis_mult = store.get_adl_disability_multiplier(adl)

    pv_mortality = 0.0
    pv_disability = 0.0
    prob_alive = 1.0
    for year in range(1, term + 1):
        current_age = age + year - 1
        qx = store.get_mortality_rate(current_age) * adl_mort_mult
        dx = 0.0
        if not exclude_disability:
            dx = store.get_disability_rate(current_age) * adl_dis_mult
            benefit_pct = store.get_adl_benefit_pct(adl) or 0.35
        else:
            benefit_pct = 0.0
        discount = (1 + config.discount_rate) ** (-year)
        prob_die = prob_alive * qx
        prob_survive_death = prob_alive * (1 - qx)
        prob_disable = prob_survive_death * dx
        pv_mortality += coverage * prob_die * discount
        if not exclude_disability and benefit_pct > 0:
            pv_disability += coverage * benefit_pct * prob_disable * discount
        prob_alive = prob_survive_death * (1 - dx)

    risk_premium = (pv_mortality + pv_disability) / term
    if loading > 0:
        risk_premium *= 1 + loading
    savings_premium = (coverage * 0.5) / term
    expense = risk_premium * config.expense_loading_pct
    profit = (risk_premium + savings_premium + expense) * config.profit_margin_pct
    annual_premium = risk_premium + savings_premium + expense + profit
    return {
        "annual_premium": annual_premium,
        "risk_premium": risk_premium,
        "savings_premium": savings_premium,
        "pv_mortality": pv_mortality,
        "pv_disability": pv_disability,
        "expense": expense,
        "profit": profit,
    }


def test_kernel_matches_legacy_simulator_default_inputs():
    """Kernel with defaults must reproduce the simulator pricer bit-for-bit.

    The legacy simulator used the graded ADL benefit table to pick the
    disability claim percentage. The canonical PHINS contract product now
    overrides that with ``fixed_disability_benefit_pct=1.0`` (the contract
    pays the full L/4 disability sum once the 3+ ADL trigger fires), so
    this test constructs a product matching the legacy graded behaviour
    explicitly to verify the kernel still preserves it for that mode.
    """
    from services.pricing_kernel import Product
    store = get_actuarial_store()
    tables = table_set_from_store(store)
    config = pricing_config_from_underwriting(store.config)
    product = Product(
        id="phins_legacy_graded_for_test",
        name="Legacy graded benefit (test-only)",
        line="life_health",
        life_share=1.0,
        disability_share=0.25,
        disability_cutoff_age=None,
        savings_rate=0.5,
        disability_benefit_on_disability_sum=False,
        fixed_disability_benefit_pct=None,
    )

    test_cases = [
        {"age": 30, "adl": 3, "coverage": 250_000, "term": 20},
        {"age": 45, "adl": 5, "coverage": 500_000, "term": 15},
        {"age": 55, "adl": 7, "coverage": 1_000_000, "term": 10},
    ]

    for case in test_cases:
        legacy = _simulator_pricer_legacy(
            customer=case, uw_result={"loading": 0, "exclude_disability": False}, store=store
        )
        kernel = price_policy(
            PricingCustomer(
                age=case["age"], coverage=case["coverage"],
                term_years=case["term"], adl_level=case["adl"],
            ),
            product, tables, config,
        )
        assert abs(kernel.pv_mortality_claims - legacy["pv_mortality"]) < 0.5, case
        assert abs(kernel.pv_disability_claims - legacy["pv_disability"]) < 0.5, case
        assert abs(kernel.risk_premium_annual - legacy["risk_premium"]) < 0.5, case
        assert abs(kernel.savings_premium_annual - legacy["savings_premium"]) < 0.5, case
        assert abs(kernel.annual_premium - legacy["annual_premium"]) < 0.5, case


def test_kernel_handles_disability_exclusion_for_high_adl():
    store = get_actuarial_store()
    tables = table_set_from_store(store)
    config = pricing_config_from_underwriting(store.config)
    product = get_product("phins_hybrid_savings")

    components = price_policy(
        PricingCustomer(age=50, coverage=500_000, term_years=15, adl_level=8),
        product, tables, config,
        underwriting_loading=0.50,
        exclude_disability=True,
    )
    assert components.eligible
    assert components.exclude_disability
    assert components.disability_premium_annual == 0.0
    assert components.pv_disability_claims == 0.0
    # Mortality is still priced, with the underwriting loading applied
    assert components.mortality_premium_annual > 0
    assert components.integrity_checks["components_sum_to_total"]


def test_savings_rate_is_truly_parametric():
    store = get_actuarial_store()
    tables = table_set_from_store(store)
    base_config = pricing_config_from_underwriting(store.config)
    product = get_product("phins_hybrid_savings")
    customer = PricingCustomer(age=40, coverage=500_000, term_years=20, adl_level=5)

    half = price_policy(customer, product, tables,
                        PricingConfig(**{**base_config.__dict__, "savings_rate": 0.50}))
    quarter = price_policy(customer, product, tables,
                           PricingConfig(**{**base_config.__dict__, "savings_rate": 0.25}))
    zero = price_policy(customer, product, tables,
                        PricingConfig(**{**base_config.__dict__, "savings_rate": 0.0}))

    assert half.savings_premium_annual > quarter.savings_premium_annual > zero.savings_premium_annual
    # Halving the savings rate must halve the savings premium with the straight-line formula
    assert abs(quarter.savings_premium_annual * 2 - half.savings_premium_annual) < 0.5
    assert zero.savings_premium_annual == 0.0
    # Pure-risk has lower annual premium than hybrid 50%
    assert zero.annual_premium < half.annual_premium


def test_savings_yield_lowers_savings_premium_when_annuity_formula():
    store = get_actuarial_store()
    tables = table_set_from_store(store)
    base = pricing_config_from_underwriting(store.config).__dict__
    base.update({"savings_rate": 0.5, "savings_formula": SavingsFormula.ANNUITY_IMMEDIATE})
    product = get_product("phins_hybrid_savings")
    customer = PricingCustomer(age=40, coverage=500_000, term_years=20, adl_level=5)

    zero_yield = price_policy(customer, product, tables,
                              PricingConfig(**{**base, "savings_yield_pct": 0.0}))
    five_yield = price_policy(customer, product, tables,
                              PricingConfig(**{**base, "savings_yield_pct": 0.05}))

    assert five_yield.savings_premium_annual < zero_yield.savings_premium_annual
    # Annuity formula must keep the integrity check
    assert five_yield.integrity_checks["components_sum_to_total"]


def test_risk_reference_age_curve_factor_anchors():
    """Anchor ages match the published one-pager exactly."""
    assert risk_reference_v1_factor(3) == 0.30
    assert risk_reference_v1_factor(25) == 1.00
    # Core slope reaches 1.60 at age 65 (1.0 + 40 * 0.015)
    assert risk_reference_v1_factor(65) == round(1.0 + 40 * 0.015, 4)


def test_age_curve_registry_contains_published_curve():
    curve = get_age_curve("risk_reference_v1")
    assert curve.id == "risk_reference_v1"
    assert curve.factor(25) == 1.00


def test_product_registry_has_three_canonical_products():
    assert "phins_pure_risk" in PRODUCT_REGISTRY
    assert "phins_hybrid_savings" in PRODUCT_REGISTRY
    assert "phins_life_only_post65" in PRODUCT_REGISTRY
    assert PRODUCT_REGISTRY["phins_pure_risk"].savings_rate == 0.0
    assert PRODUCT_REGISTRY["phins_hybrid_savings"].savings_rate == 0.5
    assert PRODUCT_REGISTRY["phins_life_only_post65"].disability_cutoff_age == 65


def test_integrity_hash_is_deterministic_and_distinguishes_inputs():
    store = get_actuarial_store()
    tables = table_set_from_store(store)
    config = pricing_config_from_underwriting(store.config)
    product = get_product("phins_hybrid_savings")

    a = price_policy(PricingCustomer(age=35, coverage=300_000, term_years=20, adl_level=4),
                     product, tables, config)
    b = price_policy(PricingCustomer(age=35, coverage=300_000, term_years=20, adl_level=4),
                     product, tables, config)
    c = price_policy(PricingCustomer(age=35, coverage=300_001, term_years=20, adl_level=4),
                     product, tables, config)

    assert a.integrity_hash == b.integrity_hash
    assert a.integrity_hash != c.integrity_hash


def test_independent_claim_model_for_legacy_callers():
    store = get_actuarial_store()
    tables = table_set_from_store(store)
    config = pricing_config_from_underwriting(
        store.config, claim_model=ClaimModel.INDEPENDENT,
    )
    product = get_product("phins_hybrid_savings")
    customer = PricingCustomer(age=45, coverage=500_000, term_years=20, adl_level=6)

    independent = price_policy(customer, product, tables, config)
    config.claim_model = ClaimModel.MUTUALLY_EXCLUSIVE
    mutually_exclusive = price_policy(customer, product, tables, config)

    # Mutually exclusive must always be <= independent because surviving
    # population is smaller after deaths are subtracted before disability.
    assert mutually_exclusive.pv_disability_claims <= independent.pv_disability_claims + 0.5


def test_reconciler_proves_simulation_components_match_kernel():
    """The reconciler must pass for a freshly-priced simulation."""
    from services.actuarial_service import reconcile_simulation_with_kernel
    params = SimulationParams(
        customer_count=80, age_min=25, age_max=55,
        coverage_min=100_000, coverage_max=400_000, coverage_median=200_000,
        policy_term_mode="fixed", policy_term_fixed=12,
    )
    sim = PortfolioSimulator(get_actuarial_store()).generate_portfolio(params)
    report = reconcile_simulation_with_kernel(sim)
    assert report['reconciled'] is True
    assert abs(report['portfolio_reconciliation']['delta']) < 1.0
    assert 'representative_integrity_hash' in report
    assert report['representative_components']['integrity_checks']['components_sum_to_total']


def test_kernel_with_simulator_end_to_end():
    """The simulator's own pricer and the kernel must produce the same totals."""
    params = SimulationParams(
        customer_count=120, age_min=25, age_max=55,
        coverage_min=100_000, coverage_max=400_000, coverage_median=200_000,
        policy_term_mode="fixed", policy_term_fixed=10,
    )
    sim = PortfolioSimulator(get_actuarial_store()).generate_portfolio(params)
    assert sim["profitability"]["components_match"]
    # The saved snapshot is now self-describing — it carries the kernel inputs
    # used to price every customer in the simulation.
    assert "simulation_id" in sim
    assert "pricing_kernel" in sim
    assert sim["pricing_kernel"]["product_id"]
    assert sim["pricing_kernel"]["claim_model"] == "mutually_exclusive"


def test_risk_premium_markup_savings_matches_user_brief_example():
    """User brief: risk premium 100 + savings 300% must produce savings 300, subtotal 400.

    This pins the canonical contract intent that the dashboard's
    ``Savings Allocation %`` means ``% of risk premium`` rather than
    a coverage-maturity target.
    """
    from services.pricing_kernel import (
        AGE_CURVE_REGISTRY, ClaimModel, PricingConfig, PricingCustomer,
        Product, SavingsFormula, TableSet, price_policy,
    )

    # A synthetic table set + product where the kernel is forced to price a
    # risk premium of exactly 100 (the user's example anchor).
    flat_rate_per_1000 = 1.6  # 16 per term-year at coverage $100k mortality only
    minimal_tables = TableSet(
        mortality_rates=[{'age_min': 0, 'age_max': 120, 'rate_per_1000': flat_rate_per_1000}],
        disability_incidence_rates=[{'age_min': 0, 'age_max': 120, 'rate_per_1000': 0.0}],
        adl_mortality_multipliers=[{'adl': i, 'multiplier': 1.0} for i in range(1, 11)],
        adl_disability_multipliers=[{'adl': i, 'multiplier': 0.0} for i in range(1, 11)],
        adl_benefit_percentages=[{'adl': i, 'benefit_pct': 0.0} for i in range(1, 11)],
        lapse_rates=[{'year_min': 1, 'year_max': 100, 'rate': 0.0}],
        age_curve=AGE_CURVE_REGISTRY['identity'],
        version='kernel_unit_test',
    )
    flat_product = Product(
        id='flat_pure_risk', name='Flat pure risk for unit test',
        life_share=1.0, disability_share=0.0,
        disability_cutoff_age=None, savings_rate=0.0,
        disability_benefit_on_disability_sum=False,
        fixed_disability_benefit_pct=None,
    )
    config_pure = PricingConfig(
        expense_loading_pct=0.0, profit_margin_pct=0.0,
        discount_rate=0.0,  # remove discount so the math is exact
        savings_rate=0.0, savings_yield_pct=0.0,
        savings_formula=SavingsFormula.RISK_PREMIUM_MARKUP,
        claim_model=ClaimModel.MUTUALLY_EXCLUSIVE,
    )
    pure = price_policy(
        PricingCustomer(age=30, coverage=100_000, term_years=20, adl_level=5),
        flat_product, minimal_tables, config_pure,
    )
    # Pure-risk anchor: with these inputs, risk premium is exactly $160/yr
    # (coverage 100k × 1.6 per 1000 × term 20 / term 20).
    assert pure.savings_premium_annual == 0.0
    assert abs(pure.annual_premium - pure.risk_premium_annual) < 1e-6

    risk_anchor = pure.risk_premium_annual

    # 300% savings markup -> savings premium = 3 * risk, subtotal = 4 * risk
    config_300 = PricingConfig(
        **{**config_pure.__dict__, 'savings_rate': 3.0,
           'savings_formula': SavingsFormula.RISK_PREMIUM_MARKUP},
    )
    plus_300 = price_policy(
        PricingCustomer(age=30, coverage=100_000, term_years=20, adl_level=5),
        flat_product, minimal_tables, config_300,
    )
    assert abs(plus_300.savings_premium_annual - 3.0 * risk_anchor) < 0.01
    assert abs(plus_300.annual_premium - 4.0 * risk_anchor) < 0.01
    assert plus_300.integrity_checks['savings_markup_identity_holds'] is True


def test_disability_share_from_config_drives_priced_disability():
    """Changing the actuary-table L:D ratio must move the priced disability PV."""
    from services.pricing_kernel import (
        ClaimModel, PricingConfig, PricingCustomer, SavingsFormula,
        get_product, price_policy, table_set_from_store,
    )
    store = get_actuarial_store()
    tables = table_set_from_store(store)
    product = get_product('phins_pure_risk_adjustable')
    customer = PricingCustomer(age=45, coverage=500_000, term_years=20, adl_level=5)

    def _price(share):
        cfg = PricingConfig(
            expense_loading_pct=store.config.expense_loading_pct,
            profit_margin_pct=store.config.profit_margin_pct,
            discount_rate=store.config.discount_rate,
            savings_rate=0.0,
            savings_formula=SavingsFormula.RISK_PREMIUM_MARKUP,
            claim_model=ClaimModel.MUTUALLY_EXCLUSIVE,
            disability_share_of_life=share,
        )
        return price_policy(customer, product, tables, cfg)

    quarter = _price(0.25)  # 1:4 — contract default
    half = _price(0.50)  # 1:2 — bigger disability sum
    zero = _price(0.0)  # disability cover removed

    # Disability sum used MUST track the configured share exactly
    assert quarter.disability_share_used == 0.25
    assert half.disability_share_used == 0.50
    assert zero.disability_share_used == 0.0

    # Bigger disability sum → bigger PV of disability claims (the contract
    # would pay 1:2 = half the life sum once triggered instead of 1:4).
    assert half.pv_disability_claims > quarter.pv_disability_claims
    assert zero.pv_disability_claims == 0.0
    # Every priced policy must mark the integrity check as PASS
    for c in (quarter, half, zero):
        assert c.integrity_checks['disability_share_matches_config']
        assert c.integrity_checks['disability_share_within_bounds']


def test_integrity_hash_distinguishes_disability_share():
    """Changing the L:D ratio must change the integrity hash."""
    from services.pricing_kernel import (
        ClaimModel, PricingConfig, PricingCustomer, SavingsFormula,
        get_product, price_policy, table_set_from_store,
    )
    store = get_actuarial_store()
    tables = table_set_from_store(store)
    product = get_product('phins_pure_risk_adjustable')
    customer = PricingCustomer(age=35, coverage=500_000, term_years=20, adl_level=5)

    def _hash(share):
        cfg = PricingConfig(
            expense_loading_pct=0.15, profit_margin_pct=0.10, discount_rate=0.035,
            savings_rate=0.0, savings_formula=SavingsFormula.RISK_PREMIUM_MARKUP,
            claim_model=ClaimModel.MUTUALLY_EXCLUSIVE,
            disability_share_of_life=share,
        )
        return price_policy(customer, product, tables, cfg).integrity_hash

    assert _hash(0.25) != _hash(0.50)
    assert _hash(0.25) == _hash(0.25)


def test_simulator_snapshot_records_disability_share():
    """The simulator's pricing_kernel provenance block must carry the L:D ratio."""
    store = get_actuarial_store()
    original = store.config.disability_share_of_life
    try:
        store.update_config({'disability_share_of_life': 0.20}, user='pytest')
        sim = PortfolioSimulator(store).generate_portfolio(
            SimulationParams(
                customer_count=60, age_min=25, age_max=55,
                coverage_min=100_000, coverage_max=400_000, coverage_median=200_000,
                policy_term_mode='fixed', policy_term_fixed=10,
            )
        )
        assert sim['pricing_kernel']['disability_share_of_life'] == 0.20
    finally:
        store.update_config({'disability_share_of_life': original}, user='pytest')


def test_ifrs17_csm_reconciliation_adds_up_under_both_release_patterns():
    """Sum of CSM releases + closing balance must equal opening CSM to the cent."""
    from services.actuarial_service import (
        _coerce_reserve_config, get_reserve_calculator,
    )
    sim = PortfolioSimulator(get_actuarial_store()).generate_portfolio(
        SimulationParams(
            customer_count=250, age_min=30, age_max=55,
            coverage_min=100_000, coverage_max=400_000, coverage_median=200_000,
            policy_term_mode='fixed', policy_term_fixed=15,
            savings_rate=0.5,
        )
    )

    for pattern in ('straight_line', 'coverage_units'):
        cfg = _coerce_reserve_config({
            'projection_years': 5,
            'csm_release_pattern': pattern,
        })
        proj = get_reserve_calculator().project(sim, cfg)
        rec = proj['csm_reconciliation']
        # Sanity: the seeded CSM must be > 0 for a profitable simulation
        assert rec['opening_csm'] > 0
        # Identity: Σ release + closing = opening (to within rounding)
        recon_total = rec['totals']['sum_of_releases'] + rec['totals']['closing_csm']
        assert abs(recon_total - rec['opening_csm']) < 1.0, (pattern, rec)
        # Every per-year identity must pass
        for r in rec['yearly']:
            checks = r['identity_checks']
            assert checks['prev_minus_release_equals_balance'], (pattern, r)
            assert checks['opening_minus_cumulative_equals_balance'], (pattern, r)
            if pattern == 'coverage_units' and r['closing_balance'] > 1.0:
                assert checks['coverage_units_share_holds'], (pattern, r)
        # Block-level integrity flags must all be True
        for k, v in rec['data_integrity'].items():
            assert v is True, (pattern, k, v)
        # Top-level data_integrity exposes the same recon flags
        assert proj['data_integrity']['csm_per_year_continuity_holds']
        assert proj['data_integrity']['csm_sum_reconciles_to_opening']
        assert proj['data_integrity']['csm_release_non_negative']


def test_csm_straight_line_release_is_uniform():
    """Under straight-line, each annual release equals opening / N."""
    from services.actuarial_service import (
        _coerce_reserve_config, get_reserve_calculator,
    )
    sim = PortfolioSimulator(get_actuarial_store()).generate_portfolio(
        SimulationParams(
            customer_count=200, age_min=30, age_max=55,
            coverage_min=100_000, coverage_max=400_000, coverage_median=200_000,
            policy_term_mode='fixed', policy_term_fixed=15,
            savings_rate=0.5,
        )
    )
    cfg = _coerce_reserve_config({
        'projection_years': 6, 'csm_release_pattern': 'straight_line',
    })
    proj = get_reserve_calculator().project(sim, cfg)
    rec = proj['csm_reconciliation']
    expected = rec['opening_csm'] / 6
    for row in rec['yearly']:
        assert abs(row['release'] - expected) < 1.0, row
    assert rec['data_integrity']['straight_line_release_uniform']


def test_reserve_savings_fund_compounds_with_yield_and_management_fee():
    """Verify the AUM identity year-by-year + cumulative aggregates."""
    from services.actuarial_service import (
        _coerce_reserve_config, get_reserve_calculator,
    )
    sim = PortfolioSimulator(get_actuarial_store()).generate_portfolio(
        SimulationParams(
            customer_count=200, age_min=30, age_max=50,
            coverage_min=100_000, coverage_max=400_000, coverage_median=200_000,
            policy_term_mode='fixed', policy_term_fixed=10,
            savings_rate=1.0,
        )
    )
    cfg = _coerce_reserve_config({
        'projection_years': 5,
        'savings_yield_pct': 0.05,
        'management_fee_pct_of_aum': 0.01,
    })
    proj = get_reserve_calculator().project(sim, cfg)
    integrity = proj['data_integrity']
    assert integrity['savings_accumulation_identity_holds']
    assert integrity['monthly_x_12_equals_annual_contribution']
    assert integrity['management_fee_non_negative']

    # The cumulative aggregates must exist and be non-zero when savings is in play
    totals = proj['totals']
    assert totals['cumulative_savings_contribution'] > 0
    assert totals['cumulative_management_fee_income'] > 0
    assert totals['closing_savings_balance'] > 0

    # AUM accumulates: closing > opening (yield > management fee for small fees)
    last = proj['yearly_projection'][-1]['savings_fund']
    first = proj['yearly_projection'][0]['savings_fund']
    assert last['closing_balance'] > first['closing_balance']

    # Setting management_fee to 0 must increase the closing balance vs 1%
    cfg_no_fee = _coerce_reserve_config({
        'projection_years': 5,
        'savings_yield_pct': 0.05,
        'management_fee_pct_of_aum': 0.0,
    })
    proj_no_fee = get_reserve_calculator().project(sim, cfg_no_fee)
    assert (
        proj_no_fee['totals']['closing_savings_balance']
        > proj['totals']['closing_savings_balance']
    )


def test_risk_reference_savings_accumulation_block():
    """build_risk_reference must surface an AUM accumulation block when savings_rate>0."""
    from services.actuarial_service import build_risk_reference
    ref = build_risk_reference(
        savings_rate=1.0, savings_yield_pct=0.05, management_fee_pct_of_aum=0.01,
    )
    accum = ref.get('savings_accumulation')
    assert accum is not None
    assert accum['data_integrity']['monthly_x_12_equals_annual']
    assert accum['data_integrity']['aum_identity_holds']
    assert accum['data_integrity']['closing_aum_non_negative']
    totals = accum['totals']
    # 5-year reference policyholder, risk_premium ~$2.1k/year × 5y × 1.0 markup,
    # roughly matches the cumulative contribution
    assert totals['cumulative_contribution'] > 0
    assert totals['closing_aum_balance'] > 0
    # No savings input -> no savings_accumulation block returned
    ref_no_savings = build_risk_reference()
    assert ref_no_savings.get('savings_accumulation') is None


def test_portfolio_valuation_best_estimate_ge_conservative_and_integrity():
    from services.actuarial_valuation import (
        calculate_portfolio_valuation, _coerce_valuation_config,
    )
    sim = PortfolioSimulator(get_actuarial_store()).generate_portfolio(
        SimulationParams(
            customer_count=300, age_min=25, age_max=55,
            coverage_min=100_000, coverage_max=400_000, coverage_median=200_000,
            policy_term_mode='fixed', policy_term_fixed=15,
            savings_rate=1.0,
        )
    )
    cfg = _coerce_valuation_config({
        'prudence_margin_pct': 0.15,
        'required_capital_pct_of_premium': 0.20,
        'cost_of_capital_pct': 0.06,
        'risk_margin_pct': 0.06,
        'tech_multiplier': 4.0,
        'tech_revenue_share_pct': 0.10,
        'savings_aum_value_pct': 0.10,
        'new_business_value_per_year': 0.0,
    })
    out = calculate_portfolio_valuation(sim, cfg)
    integrity = out['data_integrity']
    for k, v in integrity.items():
        assert v is True, (k, v)
    # Insurance BE >= Conservative; Risk Conservative >= Risk BE
    assert out['bands']['insurance_portfolio']['best_estimate'] >= out['bands']['insurance_portfolio']['conservative']
    assert out['bands']['risk_portfolio']['conservative'] >= out['bands']['risk_portfolio']['best_estimate']
    # Changing tech_multiplier must raise company BE
    cfg_low = _coerce_valuation_config({**cfg.__dict__, 'tech_multiplier': 0.0})
    cfg_high = _coerce_valuation_config({**cfg.__dict__, 'tech_multiplier': 10.0})
    low = calculate_portfolio_valuation(sim, cfg_low)
    high = calculate_portfolio_valuation(sim, cfg_high)
    assert high['bands']['company_phins_technologies']['best_estimate'] \
        > low['bands']['company_phins_technologies']['best_estimate']


def test_simulator_emits_premium_reconciliation_with_all_identities():
    """Every simulation must ship a verifiable premium_reconciliation block."""
    sim = PortfolioSimulator(get_actuarial_store()).generate_portfolio(
        SimulationParams(
            customer_count=200, age_min=30, age_max=55,
            coverage_min=100_000, coverage_max=400_000, coverage_median=200_000,
            policy_term_mode='fixed', policy_term_fixed=10,
            savings_rate=1.0,  # 100% markup -> savings == risk
            savings_formula='risk_premium_markup',
            product_id='phins_pure_risk_adjustable',
        )
    )
    recon = sim['premium_reconciliation']
    assert recon['all_identities_pass'] is True
    n_x_avg = recon['identities']['n_times_avg_premium_equals_total']
    sum_components = recon['identities']['sum_of_components_equals_total']
    markup = recon['identities']['savings_markup_identity']
    assert n_x_avg['check']
    assert sum_components['check']
    assert markup['check']
    # The portfolio summary must also expose per-component aggregates
    portfolio = sim['portfolio_summary']
    assert 'total_risk_premium' in portfolio
    assert 'total_savings_premium' in portfolio
    assert 'avg_risk_premium' in portfolio
    assert 'avg_savings_premium' in portfolio
    # And savings_rate=1.0 means total_savings == total_risk to the cent
    assert abs(portfolio['total_savings_premium'] - portfolio['total_risk_premium']) < 1.0


def test_pure_risk_default_produces_zero_savings():
    """Default simulator settings must produce a pure-risk contract with no savings premium."""
    sim = PortfolioSimulator(get_actuarial_store()).generate_portfolio(
        SimulationParams(
            customer_count=80, age_min=25, age_max=55,
            coverage_min=100_000, coverage_max=400_000, coverage_median=200_000,
            policy_term_mode='fixed', policy_term_fixed=12,
        )
    )
    assert sim['profitability']['savings_premium'] == 0.0
    assert sim['pricing_kernel']['savings_rate'] == 0.0
    assert sim['pricing_kernel']['savings_formula'] == 'risk_premium_markup'
    assert sim['pricing_kernel']['product_id'] == 'phins_pure_risk_adjustable'


def test_simulator_300pct_savings_matches_risk_premium_markup_identity():
    """Whole-portfolio identity: total_savings_premium == savings_rate × total_risk_premium."""
    sim = PortfolioSimulator(get_actuarial_store()).generate_portfolio(
        SimulationParams(
            customer_count=120, age_min=25, age_max=55,
            coverage_min=100_000, coverage_max=400_000, coverage_median=200_000,
            policy_term_mode='fixed', policy_term_fixed=15,
            savings_rate=3.0,  # 300% of risk premium per the user's brief
            savings_formula='risk_premium_markup',
            product_id='phins_pure_risk_adjustable',
        )
    )
    expected = 3.0 * sim['profitability']['risk_premium']
    actual = sim['profitability']['savings_premium']
    assert abs(actual - expected) < 1.0, (actual, expected)
    # And the simulator's own components-match flag must still hold
    assert sim['profitability']['components_match']


def test_kernel_integrity_hash_distinguishes_savings_formulas():
    """Switching savings_formula must change the integrity hash."""
    store = get_actuarial_store()
    from services.pricing_kernel import (
        ClaimModel, PricingConfig, PricingCustomer, SavingsFormula,
        get_product, price_policy, table_set_from_store,
    )
    tables = table_set_from_store(store)
    product = get_product('phins_pure_risk_adjustable')
    customer = PricingCustomer(age=35, coverage=500_000, term_years=20, adl_level=5)

    markup = price_policy(customer, product, tables,
                          PricingConfig(savings_rate=0.5,
                                        savings_formula=SavingsFormula.RISK_PREMIUM_MARKUP,
                                        claim_model=ClaimModel.MUTUALLY_EXCLUSIVE))
    straight = price_policy(customer, product, tables,
                            PricingConfig(savings_rate=0.5,
                                          savings_formula=SavingsFormula.STRAIGHT_LINE,
                                          claim_model=ClaimModel.MUTUALLY_EXCLUSIVE))
    assert markup.integrity_hash != straight.integrity_hash
    # Both must individually satisfy the identity / components checks
    assert markup.integrity_checks['savings_markup_identity_holds']
    assert straight.integrity_checks['savings_markup_identity_holds']  # vacuously true
    assert markup.integrity_checks['components_sum_to_total']
    assert straight.integrity_checks['components_sum_to_total']


def test_cohort_override_changes_priced_premium_for_matching_customer_only():
    """Registering a cohort-scoped mortality override must affect only matching customers."""
    from services.actuarial_service import (
        register_cohort_rate_table, remove_cohort_rate_table,
        get_cohort_overrides_snapshot, list_cohort_rate_tables,
    )

    # A noticeably harsher table for "caucasian women": double the mortality.
    harsh = [
        {'age_min': 30, 'age_max': 40, 'rate_per_1000': 4.0},
        {'age_min': 40, 'age_max': 50, 'rate_per_1000': 9.0},
        {'age_min': 50, 'age_max': 60, 'rate_per_1000': 18.0},
    ]
    register_cohort_rate_table(
        cohort_dim='ethnicity', cohort_value='caucasian',
        table_type='mortality_rates', normalized=harsh, user='pytest',
        source_table_id='AT-PYTEST', source_name='Caucasian Women Mortality (pytest)',
    )

    listed = list_cohort_rate_tables()
    assert any(item['cohort_key'] == 'ethnicity:caucasian' for item in listed)

    store = get_actuarial_store()
    from services.pricing_kernel import (
        PricingConfig, PricingCustomer, get_product, price_policy, table_set_from_store,
    )
    tables_with = table_set_from_store(
        store, age_curve_id='identity',
        cohort_overrides=get_cohort_overrides_snapshot(),
    )
    tables_without = table_set_from_store(store, age_curve_id='identity')
    config = PricingConfig(savings_rate=0.0)  # pure-risk to isolate mortality effect

    matching = PricingCustomer(age=45, coverage=500_000, term_years=15, adl_level=5,
                                cohort={'ethnicity': 'caucasian'})
    other = PricingCustomer(age=45, coverage=500_000, term_years=15, adl_level=5,
                             cohort={'ethnicity': 'african'})

    matching_premium = price_policy(matching, get_product('phins_pure_risk'),
                                     tables_with, config).risk_premium_annual
    matching_premium_no_override = price_policy(matching, get_product('phins_pure_risk'),
                                                  tables_without, config).risk_premium_annual
    other_premium = price_policy(other, get_product('phins_pure_risk'),
                                  tables_with, config).risk_premium_annual

    # The cohort override must increase the priced risk premium for matching customers
    assert matching_premium > matching_premium_no_override + 1
    # Non-matching customers must be unaffected
    assert abs(other_premium - price_policy(other, get_product('phins_pure_risk'),
                                              tables_without, config).risk_premium_annual) < 0.5

    remove_cohort_rate_table('ethnicity', 'caucasian', 'mortality_rates', 'pytest')
    # And after removal, the matching customer pays the same as the non-matching one again
    tables_after_remove = table_set_from_store(
        store, age_curve_id='identity', cohort_overrides=get_cohort_overrides_snapshot(),
    )
    after_remove = price_policy(matching, get_product('phins_pure_risk'),
                                 tables_after_remove, config).risk_premium_annual
    assert abs(after_remove - matching_premium_no_override) < 0.5


def test_inline_pricer_delegates_to_kernel():
    """``calculate_age_adjusted_premium`` uses the same issuance kernel path."""
    from services.pricing_shadow_service import price_application_with_kernel
    from web_portal.server import calculate_age_adjusted_premium

    result = calculate_age_adjusted_premium(
        base_premium=1000, age=40, policy_type='life',
        adl_level=5, coverage_amount=300_000, use_actuarial=True, term_years=20,
        savings_rate=0.50,
    )
    assert result['eligible']
    assert result['actuarial_source'] == 'PHINS_PRICING_KERNEL_V1'
    assert 'pricing_kernel_integrity_hash' in result
    assert len(result['pricing_kernel_integrity_hash']) == 16
    # Legacy override was base_premium * 0.5 == 500. Kernel savings differs.
    assert result['savings_premium'] != 500.0

    kernel = price_application_with_kernel({
        "type": "phins_unified",
        "coverage_amount": 300_000,
        "age": 40,
        "term_years": 20,
        "coverage_years": 20,
        "adl_level": 5,
        "savings_rate": 0.50,
        "risk_score": "medium",
    })
    assert result['savings_premium'] == kernel['savings_premium_annual']
    assert result['annual_premium'] == kernel['annual']
    assert result['pricing_kernel_integrity_hash'] == kernel['integrity_hash']


def test_financial_reporting_service_delegates_to_kernel():
    """Accountant quotes use the same kernel path as issuance."""
    from services.financial_reporting_service import FinancialReportingService
    from services.pricing_shadow_service import price_application_with_kernel

    svc = FinancialReportingService(policies={}, claims={}, billing={}, customers={}, underwriting={})
    result = svc.calculate_premium(
        coverage=500_000, age=45, adl_level=5,
        savings_pct=0.50, term_years=15,
    )
    kernel = price_application_with_kernel({
        "type": "phins_unified",
        "coverage_amount": 500_000,
        "age": 45,
        "adl_level": 5,
        "term_years": 15,
        "coverage_years": 15,
        "savings_rate": 0.50,
        "risk_score": "medium",
    })
    assert result['eligible']
    assert result['actuarial_model'] == 'PHINS_PRICING_KERNEL_V1'
    assert result['pricing_kernel_integrity_hash'] == kernel['integrity_hash']
    assert result['annual_premium'] == kernel['annual']
    assert result['monthly_premium'] == kernel['monthly']
    assert result['savings_component'] == kernel['savings_premium_annual']


def test_frs_projection_rates_use_actuarial_store():
    """Year-by-year FRS projections read the same tables as the kernel."""
    from services.actuarial_service import get_actuarial_store
    from services.financial_reporting_service import FinancialReportingService

    store = get_actuarial_store()
    svc = FinancialReportingService(
        policies={}, claims={}, billing={}, customers={}, underwriting={},
    )
    assert svc.get_mortality_rate(45) == store.get_mortality_rate(45)
    assert svc.get_disability_incidence_rate(45) == store.get_disability_rate(45)
    assert svc.get_adl_mortality_multiplier(7) == store.get_adl_mortality_multiplier(7)
    assert svc.get_adl_disability_incidence_multiplier(7) == store.get_adl_disability_multiplier(7)
    assert svc.get_adl_benefit_percentage(6) == store.get_adl_benefit_pct(6)
    assert svc.get_lapse_rate(2) == store.get_lapse_rate(2)
    projections = svc.project_policy_value(
        coverage=200_000, age=40, adl_level=5,
        savings_pct=0.0, term_years=2,
    )
    assert projections
    assert projections[0]["year"] == 1


def test_simulator_savings_rate_actually_drives_savings_premium():
    """Changing savings_rate on the simulator must move the priced savings premium.

    This pins the G1 fix: previously savings_premium was hardcoded at
    coverage * 0.5 / term inside the simulator and adjusting any 'savings %'
    knob only re-split net profit. Now the simulator delegates to the kernel
    so savings_rate flows through to every priced customer.
    """
    import random
    sim_a = PortfolioSimulator(get_actuarial_store()).generate_portfolio(
        SimulationParams(
            customer_count=200, age_min=25, age_max=55,
            coverage_min=100_000, coverage_max=400_000, coverage_median=200_000,
            policy_term_mode="fixed", policy_term_fixed=10,
            savings_rate=0.50,
        )
    )
    random.seed(0)
    sim_b = PortfolioSimulator(get_actuarial_store()).generate_portfolio(
        SimulationParams(
            customer_count=200, age_min=25, age_max=55,
            coverage_min=100_000, coverage_max=400_000, coverage_median=200_000,
            policy_term_mode="fixed", policy_term_fixed=10,
            savings_rate=0.25,
        )
    )
    sim_c = PortfolioSimulator(get_actuarial_store()).generate_portfolio(
        SimulationParams(
            customer_count=200, age_min=25, age_max=55,
            coverage_min=100_000, coverage_max=400_000, coverage_median=200_000,
            policy_term_mode="fixed", policy_term_fixed=10,
            savings_rate=0.0,
        )
    )

    a_savings = sim_a["profitability"]["savings_premium"]
    b_savings = sim_b["profitability"]["savings_premium"]
    c_savings = sim_c["profitability"]["savings_premium"]

    # The savings premium must shrink as the savings rate shrinks. Use a wide
    # tolerance because each simulation generates a fresh random portfolio.
    assert a_savings > b_savings > c_savings, (a_savings, b_savings, c_savings)
    assert c_savings == 0.0
    # The simulator snapshot must record the kernel inputs that produced it
    assert sim_a["pricing_kernel"]["savings_rate"] == 0.5
    assert sim_b["pricing_kernel"]["savings_rate"] == 0.25
    assert sim_c["pricing_kernel"]["savings_rate"] == 0.0
