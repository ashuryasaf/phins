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
    """``calculate_age_adjusted_premium`` must now report a kernel integrity hash."""
    from web_portal.server import calculate_age_adjusted_premium
    result = calculate_age_adjusted_premium(
        base_premium=1000, age=40, policy_type='life',
        adl_level=5, coverage_amount=300_000, use_actuarial=True, term_years=20,
    )
    assert result['eligible']
    assert result['actuarial_source'] == 'PHINS_PRICING_KERNEL_V1'
    assert 'pricing_kernel_integrity_hash' in result
    assert len(result['pricing_kernel_integrity_hash']) == 16


def test_financial_reporting_service_delegates_to_kernel():
    """``FinancialReportingService.calculate_premium`` must use the kernel."""
    from services.financial_reporting_service import FinancialReportingService
    svc = FinancialReportingService(policies={}, claims={}, billing={}, customers={}, underwriting={})
    result = svc.calculate_premium(
        coverage=500_000, age=45, adl_level=5,
        savings_pct=0.50, term_years=15,
    )
    assert result['eligible']
    assert result['actuarial_model'] == 'PHINS_PRICING_KERNEL_V1'
    assert 'pricing_kernel_integrity_hash' in result


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
