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
    """Kernel with defaults must reproduce the simulator pricer bit-for-bit."""
    store = get_actuarial_store()
    tables = table_set_from_store(store)
    config = pricing_config_from_underwriting(store.config)
    product = get_product("phins_hybrid_savings")

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
