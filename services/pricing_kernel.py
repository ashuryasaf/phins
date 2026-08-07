"""
PHINS Pricing Kernel — single source of truth for premium computation.

This module is the ONLY place where a premium is decomposed into its
actuarial components. Every other module in the platform (the portfolio
simulator, the inline quote/billing pricer, the financial reporting
service, the risk reference, the reserve calculator, the BI feed, and
the reconciler) calls into :func:`price_policy` to produce a
``PremiumComponents`` block. That is what makes the actuarial system
unified.

The kernel exposes:

* :class:`PremiumComponents` — canonical premium output (annual,
  monthly, mortality PV, disability PV, savings, expense, profit) with
  a deterministic integrity hash so any downstream system can prove the
  numbers were produced by the kernel and not by a parallel path.
* :class:`PricingConfig` — pricing knobs (expense, profit, discount,
  savings rate, savings yield, claim model, lapse adjustment, min-risk
  floor) versioned alongside the central tables.
* :class:`Product` and a small registry — life-only, hybrid life +
  permanent ADL disability, life-only-after-65. Product rules
  (disability cut-off age, savings rate, life share) live here, not in
  pricing call sites.
* :class:`AgeCurve` and a registry — currently ``phins_internal_v2``
  (the tables-driven curve used by the platform today) and
  ``risk_reference_v1`` (the locked actuarial source block published on
  ``phins.ai/phins-risk-1pager-fefferman.html``). New curves can be
  registered without touching pricing code.
* :class:`TableSet` — a snapshot view over the central
  :class:`ActuarialTablesStore` (extended later with cohort-scoped
  overrides for uploaded tables).

The mortality / disability math is parameterised on a *claim model*:

* ``ClaimModel.MUTUALLY_EXCLUSIVE`` — a policyholder can claim either
  mortality OR disability in a given lifetime, never both. This matches
  the actuarial standard for life insurance and is the more rigorous
  pricing model. It is the default.
* ``ClaimModel.INDEPENDENT`` — mortality and disability incidence are
  priced independently over the surviving population each year. This
  matches the legacy ``calculate_age_adjusted_premium`` and
  ``FinancialReportingService.calculate_premium`` math and is retained
  so we can migrate those call sites without changing their outputs.

Savings premium is parameterised: ``savings_premium = target_value ×
annuity_contribution_factor(yield, term)``, where ``target_value =
coverage × savings_rate``. With ``savings_yield_pct = 0`` and
``savings_rate = 0.5`` the formula reduces to
``coverage × 0.5 / term`` — exactly the legacy hardcoded value — so the
default behaviour is preserved bit-for-bit.

The kernel never mutates inputs. Every output is rounded to 6 decimal
places before hashing so the integrity hash is reproducible across
hosts.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


# =============================================================================
# ENUMS
# =============================================================================

class ClaimModel(str, Enum):
    """How mortality and disability claims interact."""

    MUTUALLY_EXCLUSIVE = "mutually_exclusive"  # rigorous: a policy pays one major claim
    INDEPENDENT = "independent"  # legacy: each priced independently


class SavingsFormula(str, Enum):
    """How the savings premium is derived.

    Three formulas are supported. The first two model savings as a target
    maturity value over the policy term. The third — the canonical PHINS
    formula — models savings as a markup on the priced risk premium and is
    the default for the actuary dashboard's portfolio simulator.

    * ``RISK_PREMIUM_MARKUP`` — ``savings_premium = risk_premium ×
      savings_rate`` (savings_rate can exceed 100%, e.g. 3.0 = 300%).
      Matches the contract intent: the customer's pure-risk premium is
      computed first from age/sex/smoker/underwriting, then the customer
      can elect a savings add-on as a multiple of that premium.
    * ``STRAIGHT_LINE`` — ``savings_premium = coverage × savings_rate /
      term``. Legacy coverage-maturity formula retained for backwards
      compatibility with existing reports.
    * ``ANNUITY_IMMEDIATE`` — ``savings_premium = (coverage × savings_rate)
      × yield_rate / ((1+yield_rate)^term - 1)``. Legacy formula that
      discounts the savings target at the assumed yield.
    """

    RISK_PREMIUM_MARKUP = "risk_premium_markup"
    STRAIGHT_LINE = "straight_line"
    ANNUITY_IMMEDIATE = "annuity_immediate"


# =============================================================================
# DATACLASSES
# =============================================================================

@dataclass(frozen=True)
class PricingCustomer:
    """Minimal customer view consumed by the kernel."""

    age: int
    coverage: float
    term_years: int
    adl_level: int = 5
    gender: Optional[str] = None
    # Smoking status: never/nonsmoker | former | current/smoker. When unset,
    # demographic smoking multipliers stay neutral (1.0).
    smoking_status: Optional[str] = None
    # Ethnicity key matched against PricingConfig.ethnicity_*_factors
    # (e.g. caucasian/african/hispanic/asian/other). Also read from cohort.
    ethnicity: Optional[str] = None
    cohort: Dict[str, str] = field(default_factory=dict)
    # When ``annual_premium_target`` is set, the kernel still returns the
    # decomposed components but uses this as a sanity hint for downstream
    # reconciliation (the kernel itself does not adjust outputs to match it).
    annual_premium_target: Optional[float] = None


@dataclass(frozen=True)
class Product:
    """Insurance product rules that drive the pricing kernel."""

    id: str
    name: str
    line: str = "life_health"
    life_share: float = 1.0
    disability_share: float = 0.25  # disability sum = coverage * disability_share
    disability_cutoff_age: Optional[int] = None
    savings_rate: float = 0.0  # legacy share of coverage targeted as savings maturity value
    # When True the disability benefit is paid as a percentage of the disability
    # sum (life_share × disability_share × coverage) rather than the full
    # mortality coverage. False keeps the legacy behaviour of paying as a
    # percentage of full coverage.
    disability_benefit_on_disability_sum: bool = False
    # When set (0.0–1.0), the kernel ignores the ADL benefit table and pays
    # this fixed percentage of the disability sum on any qualifying claim.
    # The PHINS pure-risk contract uses ``fixed_disability_benefit_pct=1.0``
    # because once the 3+ ADL trigger fires the contract pays the full
    # L/4 disability sum regardless of the customer's current ADL severity.
    fixed_disability_benefit_pct: Optional[float] = None
    description: str = ""


@dataclass(frozen=True)
class AgeCurve:
    """Multiplicative age factor curve attached to a TableSet."""

    id: str
    description: str = ""
    # When None the kernel uses the mortality/disability tables only; the age
    # curve factor multiplies the mortality and disability rates by the value
    # returned from ``factor(age)``. The default identity curve returns 1.0 so
    # no age factor is applied (the rate tables already encode age dependence).
    factor_fn: Any = None  # callable(age:int) -> float

    def factor(self, age: int) -> float:
        if self.factor_fn is None:
            return 1.0
        try:
            return float(self.factor_fn(int(age)))
        except Exception:
            return 1.0


@dataclass
class PricingConfig:
    """Versioned pricing knobs read by every kernel call."""

    expense_loading_pct: float = 0.15
    profit_margin_pct: float = 0.10
    discount_rate: float = 0.035
    savings_rate: float = 0.5  # legacy default: 50% of coverage as maturity target
    savings_yield_pct: float = 0.0  # legacy default: no yield assumption
    savings_formula: SavingsFormula = SavingsFormula.STRAIGHT_LINE
    claim_model: ClaimModel = ClaimModel.MUTUALLY_EXCLUSIVE
    apply_lapse_adjustment: bool = False
    apply_min_risk_floor: bool = False
    expense_basis: str = "risk_premium"  # 'risk_premium' or 'gross_premium'
    profit_basis: str = "risk_savings_expense"  # 'risk_savings_expense' or 'gross_premium'
    # Contract ratio between the disability benefit and the *attained-age life
    # sum* for ages below ``disability_band_age``. Default 0.25 → D = life/4
    # while life = full coverage (pre-65: L=$500k, D=$125k).
    disability_share_of_life: Optional[float] = None
    # Post-band D/life ratio. Default 1.0 → disability equals the post-65 life
    # sum (both $125k when coverage=$500k and life_share_post65=0.25).
    disability_share_of_life_post65: Optional[float] = 1.0
    # Life sum as a fraction of coverage. Pre-65 default 1.0 (full L);
    # post-65 default 0.25 (life steps down to L/4).
    life_share_of_coverage: float = 1.0
    life_share_of_coverage_post65: float = 0.25
    disability_band_age: int = 65
    # Post-disability administration (does not change healthy-life quote PV
    # while claim_model stays MUTUALLY_EXCLUSIVE). Default premium factor
    # 1.0 = continue charging 100% of the pre-claim combined premium.
    pre65_disability_continues_policy: bool = True
    post_disability_life_share_of_face: float = 0.75
    post_disability_premium_factor: float = 1.0
    post65_claims_mutually_exclusive: bool = True
    # Demographic rate multipliers (dashboard-adjustable). Defaults are 1.0
    # (neutral) so existing unisex/unismoker pricing is unchanged until the
    # actuary tunes them. Applied separately to mortality (life) and
    # disability incidence rates, then stamped into the integrity hash.
    smoker_mortality_factor: float = 1.0
    smoker_disability_factor: float = 1.0
    former_smoker_mortality_factor: float = 1.0
    former_smoker_disability_factor: float = 1.0
    nonsmoker_mortality_factor: float = 1.0
    nonsmoker_disability_factor: float = 1.0
    male_mortality_factor: float = 1.0
    male_disability_factor: float = 1.0
    female_mortality_factor: float = 1.0
    female_disability_factor: float = 1.0
    ethnicity_mortality_factors: Dict[str, float] = field(default_factory=lambda: {
        "caucasian": 1.0,
        "african": 1.0,
        "hispanic": 1.0,
        "asian": 1.0,
        "other": 1.0,
    })
    ethnicity_disability_factors: Dict[str, float] = field(default_factory=lambda: {
        "caucasian": 1.0,
        "african": 1.0,
        "hispanic": 1.0,
        "asian": 1.0,
        "other": 1.0,
    })
    version: str = "kernel_v1"


@dataclass
class TableSet:
    """
    Snapshot of the central actuarial tables consumed by the kernel.

    Holding the snapshot in this object instead of reaching into the global
    store directly makes pricing deterministic: a kernel call always sees the
    same numbers from start to finish even if the store mutates concurrently.
    Cohort-scoped uploaded tables (e.g. mortality for Caucasian women) will be
    layered on top of ``mortality_rates``/``disability_incidence_rates`` via
    ``cohort_overrides`` in a follow-up commit.
    """

    mortality_rates: List[Dict[str, Any]]
    disability_incidence_rates: List[Dict[str, Any]]
    adl_mortality_multipliers: List[Dict[str, Any]]
    adl_disability_multipliers: List[Dict[str, Any]]
    adl_benefit_percentages: List[Dict[str, Any]]
    lapse_rates: List[Dict[str, Any]]
    age_curve: AgeCurve = field(default_factory=lambda: AGE_CURVE_REGISTRY["identity"])
    version: str = "central_v2"
    cohort_overrides: Dict[str, Dict[str, List[Dict[str, Any]]]] = field(default_factory=dict)

    def _lookup_bracket(self, table: List[Dict[str, Any]], age: int) -> float:
        for row in table:
            if int(row.get("age_min", 0)) <= age < int(row.get("age_max", 0)):
                return float(row.get("rate_per_1000", 0.0)) / 1000.0
        return 0.0

    def _select_cohort_table(self, base: List[Dict[str, Any]], cohort: Dict[str, str],
                             kind: str) -> List[Dict[str, Any]]:
        if not cohort or not self.cohort_overrides:
            return base
        for key, value in cohort.items():
            override = self.cohort_overrides.get(f"{key}:{value}", {}).get(kind)
            if override:
                return self._merge_tables(base, override)
        return base

    @staticmethod
    def _merge_tables(base: List[Dict[str, Any]], override: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Merge a partial cohort override onto the base rate table.

        For age brackets covered by the override, the override row is used.
        Brackets in the base table that are not covered by any override row
        are retained so that uncovered ages fall back to the global rate
        instead of silently returning 0.0.
        """
        override_ranges = {
            (int(r.get("age_min", 0)), int(r.get("age_max", 0))) for r in override
        }
        merged = list(override)
        for row in base:
            bracket = (int(row.get("age_min", 0)), int(row.get("age_max", 0)))
            if bracket not in override_ranges:
                merged.append(row)
        return merged

    def mortality_qx(self, age: int, cohort: Optional[Dict[str, str]] = None) -> float:
        table = self._select_cohort_table(self.mortality_rates, cohort or {}, "mortality_rates")
        return self._lookup_bracket(table, age) * self.age_curve.factor(age)

    def disability_ix(self, age: int, cohort: Optional[Dict[str, str]] = None) -> float:
        table = self._select_cohort_table(
            self.disability_incidence_rates, cohort or {}, "disability_incidence_rates"
        )
        return self._lookup_bracket(table, age) * self.age_curve.factor(age)

    def adl_mortality_multiplier(self, adl: int) -> float:
        for row in self.adl_mortality_multipliers:
            if int(row.get("adl", 0)) == int(adl):
                return float(row.get("multiplier", 1.0))
        return 1.0

    def adl_disability_multiplier(self, adl: int) -> float:
        for row in self.adl_disability_multipliers:
            if int(row.get("adl", 0)) == int(adl):
                return float(row.get("multiplier", 1.0))
        return 1.0

    def adl_benefit_pct(self, adl: int) -> float:
        for row in self.adl_benefit_percentages:
            if int(row.get("adl", 0)) == int(adl):
                return float(row.get("benefit_pct", 0.0))
        return 0.0

    def lapse_rate(self, year: int) -> float:
        for row in self.lapse_rates:
            if "year" in row and int(row["year"]) == year:
                return float(row.get("rate", 0.0))
            if (
                "year_min" in row
                and int(row["year_min"]) <= year <= int(row.get("year_max", 0))
            ):
                return float(row.get("rate", 0.0))
        return 0.0


# =============================================================================
# AGE CURVE REGISTRY
# =============================================================================
#
# The platform ships with two curves:
#
# * ``identity`` — multiplicative factor 1.0 at every age; the age dependence
#   lives entirely in the rate tables (this is how the production simulator
#   has always worked and is the default).
# * ``risk_reference_v1`` — locked actuarial source block published on
#   ``phins.ai/phins-risk-1pager-fefferman.html``. Exposed here so the same
#   kernel can reproduce that curve for risk-reference purposes and so that
#   future products can opt into it.
#
# Adding a new curve is a single ``register_age_curve(AgeCurve(...))`` call;
# pricing call sites do not need to change.
# =============================================================================


RISK_REFERENCE_V1_PARAMS: Dict[str, float] = {
    "youth_anchor_age": 3,
    "youth_anchor_factor": 0.30,
    "adult_anchor_age": 25,
    "adult_anchor_factor": 1.00,
    "core_slope": 0.015,
    "disability_cut_off_age": 65,
    "senior_slope_1": 0.05,
    "senior_slope_2": 0.08,
}


def risk_reference_v1_factor(age: int) -> float:
    """The published age curve from the public risk one-pager."""
    p = RISK_REFERENCE_V1_PARAMS
    age = int(age)
    if age <= p["adult_anchor_age"]:
        span = p["adult_anchor_age"] - p["youth_anchor_age"]
        rise = p["adult_anchor_factor"] - p["youth_anchor_factor"]
        anchored = max(p["youth_anchor_age"], age)
        return round(
            p["youth_anchor_factor"] + (anchored - p["youth_anchor_age"]) * (rise / span),
            4,
        )
    if age <= p["disability_cut_off_age"]:
        return round(
            p["adult_anchor_factor"] + (age - p["adult_anchor_age"]) * p["core_slope"], 4
        )
    base = risk_reference_v1_factor(int(p["disability_cut_off_age"]))
    capped = min(age, 80)
    if capped <= 75:
        return round(base + (capped - p["disability_cut_off_age"]) * p["senior_slope_1"], 4)
    return round(
        base
        + (75 - p["disability_cut_off_age"]) * p["senior_slope_1"]
        + (capped - 75) * p["senior_slope_2"],
        4,
    )


AGE_CURVE_REGISTRY: Dict[str, AgeCurve] = {
    "identity": AgeCurve(
        id="identity",
        description="Multiplicative factor 1.0 — age dependence lives entirely in the rate tables.",
        factor_fn=None,
    ),
    "risk_reference_v1": AgeCurve(
        id="risk_reference_v1",
        description=(
            "Locked actuarial source block on phins.ai/phins-risk-1pager-fefferman.html "
            "— youth/adult/senior age factor curve used to reproduce the public one-pager."
        ),
        factor_fn=risk_reference_v1_factor,
    ),
}


def register_age_curve(curve: AgeCurve) -> AgeCurve:
    """Register an age curve in the global registry."""
    AGE_CURVE_REGISTRY[curve.id] = curve
    return curve


def get_age_curve(curve_id: str) -> AgeCurve:
    return AGE_CURVE_REGISTRY.get(curve_id or "identity", AGE_CURVE_REGISTRY["identity"])


# =============================================================================
# PRODUCT REGISTRY
# =============================================================================

PRODUCT_REGISTRY: Dict[str, Product] = {
    # Canonical PHINS contract — matches the published risk one-pager and the
    # contract draft governing the actuary dashboard. Life cover from age 3
    # through ∞, permanent ADL disability cover from age 3 through 65 paying
    # L/4 on trigger, no savings/cash-value/surrender/investment component.
    "phins_pure_risk_adjustable": Product(
        id="phins_pure_risk_adjustable",
        name="PHINS Adjustable Risk (pre-65 L/D=4:1; post-65 life÷4 & D=life)",
        line="life_health",
        life_share=1.0,
        disability_share=0.25,
        disability_cutoff_age=65,  # band age; post-65 shares from PricingConfig
        savings_rate=0.0,
        disability_benefit_on_disability_sum=True,
        fixed_disability_benefit_pct=1.0,
        description=(
            "PHINS Adjustable Risk contract. Before 65: life = face (e.g. $500k) and "
            "disability = life/4 ($125k). From age 65+: life steps down to face/4 "
            "($125k) and disability equals that reduced life sum ($125k). Shares are "
            "age-banded from actuary config. Pure risk — no savings/cash value."
        ),
    ),
    # Back-compat alias: the previous 'phins_pure_risk' product id is now an
    # alias for the contract-draft-aligned product.
    "phins_pure_risk": Product(
        id="phins_pure_risk",
        name="PHINS Adjustable Risk (pre-65 L/D=4:1; post-65 life÷4 & D=life)",
        line="life_health",
        life_share=1.0,
        disability_share=0.25,
        disability_cutoff_age=65,
        savings_rate=0.0,
        disability_benefit_on_disability_sum=True,
        fixed_disability_benefit_pct=1.0,
        description="Alias of phins_pure_risk_adjustable kept for backwards compatibility.",
    ),
    # Hybrid product = pure-risk cover + an optional savings ADD-ON priced as
    # a markup on the risk premium (savings_rate semantics depend on the
    # PricingConfig.savings_formula). With RISK_PREMIUM_MARKUP and
    # savings_rate=1.0 the savings premium equals the risk premium; with
    # savings_rate=3.0 (300%) the savings premium is three times the risk
    # premium; with savings_rate=0.0 the product collapses back to pure risk.
    "phins_hybrid_savings": Product(
        id="phins_hybrid_savings",
        name="PHINS Risk + Savings Add-on",
        line="life_health_savings",
        life_share=1.0,
        disability_share=0.25,
        disability_cutoff_age=65,
        savings_rate=0.5,
        disability_benefit_on_disability_sum=True,
        fixed_disability_benefit_pct=1.0,
        description=(
            "PHINS Adjustable Risk cover with an optional savings add-on. The "
            "default savings_rate=0.5 means the customer elects 50% of the risk "
            "premium as a savings contribution (RISK_PREMIUM_MARKUP formula); the "
            "rate can be any value, e.g. 3.0 = 300% of risk premium per the "
            "user's example."
        ),
    ),
    "phins_life_only_post65": Product(
        id="phins_life_only_post65",
        name="PHINS Life-only (post age 65)",
        line="life_only",
        life_share=1.0,
        disability_share=0.0,
        disability_cutoff_age=65,
        savings_rate=0.0,
        disability_benefit_on_disability_sum=False,
        fixed_disability_benefit_pct=None,
        description=(
            "Senior life-only cover; disability benefit terminates at age 65 and "
            "the death benefit re-prices on the senior age curve."
        ),
    ),
}


def register_product(product: Product) -> Product:
    PRODUCT_REGISTRY[product.id] = product
    return product


def get_product(product_id: str) -> Product:
    return PRODUCT_REGISTRY.get(product_id, PRODUCT_REGISTRY["phins_hybrid_savings"])


# =============================================================================
# PREMIUM COMPONENTS + KERNEL
# =============================================================================

@dataclass
class PremiumComponents:
    """Canonical premium decomposition produced by the kernel."""

    annual_premium: float
    monthly_premium: float
    risk_premium_annual: float
    mortality_premium_annual: float
    disability_premium_annual: float
    savings_premium_annual: float
    expense_loading_annual: float
    profit_margin_annual: float
    pv_mortality_claims: float
    pv_disability_claims: float
    pv_total_risk_claims: float
    eligible: bool = True
    decline_reason: Optional[str] = None
    coverage_amount: float = 0.0
    term_years: int = 0
    age: int = 0
    adl_level: int = 0
    adl_mortality_multiplier: float = 1.0
    adl_disability_multiplier: float = 1.0
    benefit_pct_used: float = 0.0
    exclude_disability: bool = False
    underwriting_loading: float = 0.0
    age_factor: float = 1.0
    age_curve_id: str = "identity"
    product_id: str = "phins_hybrid_savings"
    tables_version: str = ""
    config_version: str = "kernel_v1"
    actuarial_source: str = "PHINS_PRICING_KERNEL_V1"
    claim_model: str = ClaimModel.MUTUALLY_EXCLUSIVE.value
    savings_formula: str = SavingsFormula.STRAIGHT_LINE.value
    savings_rate_used: float = 0.0
    savings_yield_used: float = 0.0
    # The contract ratio between the disability sum and the life sum (L)
    # actually applied to this priced policy. Sourced from
    # PricingConfig.disability_share_of_life when set, else from
    # Product.disability_share. Surfaced here so the actuary dashboard,
    # audit reports and the reconciler can prove every priced policy used
    # the same actuary-table-driven ratio.
    disability_share_used: float = 0.25
    disability_sum_used: float = 0.0
    life_share_used: float = 1.0
    life_sum_used: float = 0.0
    # Post-disability administration knobs stamped for audit (quote PV
    # remains mutually exclusive by default — combined premium unchanged).
    post_disability_premium_factor: float = 1.0
    post_disability_life_share_of_face: float = 0.75
    pre65_disability_continues_policy: bool = True
    post65_claims_mutually_exclusive: bool = True
    # Composite demographic multipliers actually applied to this price
    # (smoking × sex × ethnicity), plus the resolved attribute labels.
    demographic_mortality_factor: float = 1.0
    demographic_disability_factor: float = 1.0
    smoking_status_used: Optional[str] = None
    gender_used: Optional[str] = None
    ethnicity_used: Optional[str] = None
    demographic_factors_applied: Dict[str, Any] = field(default_factory=dict)
    integrity_hash: str = ""
    integrity_checks: Dict[str, bool] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _annuity_contribution_factor(yield_rate: float, term: int) -> float:
    """Periodic contribution that grows to 1.0 at the end of ``term`` years."""
    term = max(1, int(term))
    if abs(yield_rate) < 1e-9:
        return 1.0 / term
    growth = (1.0 + yield_rate) ** term
    if growth - 1.0 == 0:
        return 1.0 / term
    return yield_rate / (growth - 1.0)


def _compute_savings_premium(
    coverage: float,
    term_years: int,
    product: Product,
    config: PricingConfig,
    risk_premium_annual: float,
) -> float:
    """Compute the savings premium component using the configured formula.

    The canonical PHINS formula is ``RISK_PREMIUM_MARKUP``: a customer who
    elects ``savings_rate`` pays ``savings_rate × risk_premium`` per year on
    top of the priced risk premium. ``savings_rate`` is unbounded — 0.0 means
    pure risk, 1.0 means matching the risk premium, 3.0 means three times
    the risk premium (the example from the user's brief).
    """
    savings_rate = max(0.0, float(config.savings_rate))
    if savings_rate == 0.0 or term_years <= 0:
        return 0.0
    if config.savings_formula == SavingsFormula.RISK_PREMIUM_MARKUP:
        return max(0.0, float(risk_premium_annual)) * savings_rate
    # Legacy maturity-target formulas
    target_value = coverage * savings_rate * product.life_share
    if target_value <= 0:
        return 0.0
    if config.savings_formula == SavingsFormula.ANNUITY_IMMEDIATE and abs(config.savings_yield_pct) > 1e-12:
        factor = _annuity_contribution_factor(float(config.savings_yield_pct), int(term_years))
        return target_value * factor
    return target_value / float(term_years)


def _band_age(config: PricingConfig) -> int:
    return int(getattr(config, "disability_band_age", 65) or 65)


def _resolve_life_share(product: Product, config: PricingConfig,
                        age: Optional[int] = None) -> float:
    """Life sum as a fraction of coverage for an attained age.

    Pre-65 default 1.0 (full L). Post-65 default 0.25 (life steps to face/4).
    """
    configured_pre = getattr(config, "life_share_of_coverage", None)
    if configured_pre is None:
        pre = float(product.life_share or 1.0)
    else:
        pre = float(configured_pre)
    post = float(getattr(config, "life_share_of_coverage_post65", 0.25))
    if age is None:
        return pre
    return post if int(age) >= _band_age(config) else pre


def _resolve_disability_share(product: Product, config: PricingConfig,
                              age: Optional[int] = None) -> float:
    """Resolve D / life_sum share for an attained age (age-banded contract).

    Bands (current product rule):
      * age < band → D = life/4 (share 0.25) with life = full coverage
        → e.g. L=$500k, D=$125k
      * age >= band → life = coverage/4 and D = life (share 1.0)
        → e.g. life=$125k, D=$125k

    When ``disability_share_of_life_post65`` is None, legacy cutoff-to-zero
    behavior is kept.
    """
    if float(product.disability_share) <= 0.0 and config.disability_share_of_life is None:
        return 0.0

    pre = (
        float(config.disability_share_of_life)
        if config.disability_share_of_life is not None
        else float(product.disability_share)
    )
    post = config.disability_share_of_life_post65
    band = _band_age(config)

    if age is None:
        return pre

    age_i = int(age)
    if post is None:
        if product.disability_cutoff_age is not None and age_i >= int(product.disability_cutoff_age):
            return 0.0
        return pre

    return float(post) if age_i >= band else pre


def _normalize_smoking_status(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    if s in ("current", "smoker", "yes", "true", "1", "y"):
        return "smoker"
    if s in ("former", "ex", "ex_smoker", "exsmoker"):
        return "former"
    if s in ("never", "nonsmoker", "non_smoker", "no", "false", "0", "n"):
        return "nonsmoker"
    return None


def _normalize_sex(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in ("m", "male", "man"):
        return "male"
    if s in ("f", "female", "woman"):
        return "female"
    return None


def _normalize_ethnicity(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "caucasian": "caucasian",
        "white": "caucasian",
        "african": "african",
        "black": "african",
        "african_american": "african",
        "hispanic": "hispanic",
        "latino": "hispanic",
        "latina": "hispanic",
        "asian": "asian",
        "other": "other",
    }
    return aliases.get(s)


def resolve_demographic_rate_factors(
    customer: PricingCustomer,
    config: PricingConfig,
) -> Dict[str, Any]:
    """Resolve smoking × sex × ethnicity multipliers for life and disability.

    Missing attributes stay neutral (factor 1.0). Config defaults are also 1.0
    so enabling a factor requires an explicit actuary dashboard change.
    """
    cohort = customer.cohort or {}
    smoking = _normalize_smoking_status(
        customer.smoking_status
        or cohort.get("smoker")
        or cohort.get("smoking")
        or cohort.get("smoking_status")
    )
    sex = _normalize_sex(
        customer.gender or cohort.get("gender") or cohort.get("sex")
    )
    ethnicity = _normalize_ethnicity(
        customer.ethnicity or cohort.get("ethnicity") or cohort.get("race")
    )

    smoke_mort = 1.0
    smoke_dis = 1.0
    if smoking == "smoker":
        smoke_mort = float(config.smoker_mortality_factor)
        smoke_dis = float(config.smoker_disability_factor)
    elif smoking == "former":
        smoke_mort = float(config.former_smoker_mortality_factor)
        smoke_dis = float(config.former_smoker_disability_factor)
    elif smoking == "nonsmoker":
        smoke_mort = float(config.nonsmoker_mortality_factor)
        smoke_dis = float(config.nonsmoker_disability_factor)

    sex_mort = 1.0
    sex_dis = 1.0
    if sex == "male":
        sex_mort = float(config.male_mortality_factor)
        sex_dis = float(config.male_disability_factor)
    elif sex == "female":
        sex_mort = float(config.female_mortality_factor)
        sex_dis = float(config.female_disability_factor)

    eth_mort_map = dict(config.ethnicity_mortality_factors or {})
    eth_dis_map = dict(config.ethnicity_disability_factors or {})
    eth_mort = float(eth_mort_map.get(ethnicity, 1.0)) if ethnicity else 1.0
    eth_dis = float(eth_dis_map.get(ethnicity, 1.0)) if ethnicity else 1.0

    mort = max(0.0, smoke_mort * sex_mort * eth_mort)
    dis = max(0.0, smoke_dis * sex_dis * eth_dis)
    applied = {
        "smoking": smoking,
        "sex": sex,
        "ethnicity": ethnicity,
        "smoking_mortality": _round6(smoke_mort),
        "smoking_disability": _round6(smoke_dis),
        "sex_mortality": _round6(sex_mort),
        "sex_disability": _round6(sex_dis),
        "ethnicity_mortality": _round6(eth_mort),
        "ethnicity_disability": _round6(eth_dis),
    }
    return {
        "mortality_factor": mort,
        "disability_factor": dis,
        "applied": applied,
        "smoking": smoking,
        "sex": sex,
        "ethnicity": ethnicity,
    }


def _benefit_sums_for_age(coverage: float, product: Product, config: PricingConfig,
                          age: int) -> Dict[str, float]:
    """Return life_sum and disability_sum for an attained age.

    When ``disability_benefit_on_disability_sum`` is True (canonical contract),
    disability_sum = life_sum × D/life share. When False (legacy graded mode),
    disability_sum = life_sum and the ADL benefit % is applied later — matching
    the historical "percentage of full coverage" path.
    """
    life_share = _resolve_life_share(product, config, age)
    dis_share = _resolve_disability_share(product, config, age)
    life_sum = coverage * life_share
    if product.disability_benefit_on_disability_sum:
        disability_sum = life_sum * dis_share
    else:
        disability_sum = life_sum
    return {
        "life_share": life_share,
        "disability_share": dis_share,
        "life_sum": life_sum,
        "disability_sum": disability_sum,
    }


def _pv_claims_mutually_exclusive(
    customer: PricingCustomer,
    product: Product,
    tables: TableSet,
    config: PricingConfig,
    benefit_pct: float,
    exclude_disability: bool,
    adl_mort_mult: float,
    adl_dis_mult: float,
) -> Dict[str, float]:
    """Mutual-exclusivity PV of mortality + disability claims (simulator method)."""
    age = int(customer.age)
    coverage = float(customer.coverage)
    term = int(customer.term_years)
    discount_rate = float(config.discount_rate)
    demo = resolve_demographic_rate_factors(customer, config)
    demo_mort = float(demo["mortality_factor"])
    demo_dis = float(demo["disability_factor"])

    pv_mortality = 0.0
    pv_disability = 0.0
    prob_alive_not_disabled = 1.0

    for year in range(1, term + 1):
        current_age = age + year - 1
        qx = tables.mortality_qx(current_age, customer.cohort) * adl_mort_mult * demo_mort
        sums = _benefit_sums_for_age(coverage, product, config, current_age)
        share = sums["disability_share"]
        life_sum = sums["life_sum"]
        disability_sum = sums["disability_sum"]

        disability_active = (
            not exclude_disability
            and product.disability_share > 0.0
            and share > 0.0
        )
        dx = (
            tables.disability_ix(current_age, customer.cohort) * adl_dis_mult * demo_dis
            if disability_active
            else 0.0
        )

        discount = (1.0 + discount_rate) ** (-year)
        if config.apply_lapse_adjustment:
            lapse_survival = 1.0
            for y in range(1, year + 1):
                lapse_survival *= max(0.0, 1.0 - tables.lapse_rate(y))
            discount *= lapse_survival

        prob_die_this_year = prob_alive_not_disabled * qx
        prob_survive_death = prob_alive_not_disabled * max(0.0, 1.0 - qx)
        prob_disable_this_year = prob_survive_death * dx

        pv_mortality += life_sum * prob_die_this_year * discount
        if disability_active and benefit_pct > 0:
            pv_disability += disability_sum * benefit_pct * prob_disable_this_year * discount

        prob_alive_not_disabled = prob_survive_death * max(0.0, 1.0 - dx)

    return {"pv_mortality": pv_mortality, "pv_disability": pv_disability}


def _pv_claims_independent(
    customer: PricingCustomer,
    product: Product,
    tables: TableSet,
    config: PricingConfig,
    benefit_pct: float,
    exclude_disability: bool,
    adl_mort_mult: float,
    adl_dis_mult: float,
) -> Dict[str, float]:
    """Independent mortality and disability PV (legacy method used by inline pricer/FRS)."""
    age = int(customer.age)
    coverage = float(customer.coverage)
    term = int(customer.term_years)
    discount_rate = float(config.discount_rate)
    demo = resolve_demographic_rate_factors(customer, config)
    demo_mort = float(demo["mortality_factor"])
    demo_dis = float(demo["disability_factor"])

    pv_mortality = 0.0
    for year in range(1, term + 1):
        current_age = age + year - 1
        qx = tables.mortality_qx(current_age, customer.cohort) * adl_mort_mult * demo_mort
        life_sum = _benefit_sums_for_age(coverage, product, config, current_age)["life_sum"]
        px_prev = 1.0
        for y in range(year - 1):
            px_prev *= max(
                0.0,
                1.0 - tables.mortality_qx(age + y, customer.cohort) * adl_mort_mult * demo_mort,
            )
        death_prob = px_prev * qx
        discount = (1.0 + discount_rate) ** (-year)
        if config.apply_lapse_adjustment:
            lapse_survival = 1.0
            for y in range(1, year + 1):
                lapse_survival *= max(0.0, 1.0 - tables.lapse_rate(y))
            discount *= lapse_survival
        pv_mortality += life_sum * death_prob * discount

    pv_disability = 0.0
    if not exclude_disability and product.disability_share > 0.0:
        for year in range(1, term + 1):
            current_age = age + year - 1
            sums = _benefit_sums_for_age(coverage, product, config, current_age)
            share = sums["disability_share"]
            if share <= 0.0:
                continue
            disability_sum = sums["disability_sum"]
            survival = 1.0
            for y in range(year - 1):
                survival *= max(
                    0.0,
                    1.0 - tables.mortality_qx(age + y, customer.cohort) * adl_mort_mult * demo_mort,
                )
            dis_rate = (
                tables.disability_ix(current_age, customer.cohort) * adl_dis_mult * demo_dis
            )
            discount = (1.0 + discount_rate) ** (-year)
            if config.apply_lapse_adjustment:
                lapse_survival = 1.0
                for y in range(1, year + 1):
                    lapse_survival *= max(0.0, 1.0 - tables.lapse_rate(y))
                discount *= lapse_survival
            pv_disability += survival * dis_rate * disability_sum * benefit_pct * discount

    return {"pv_mortality": pv_mortality, "pv_disability": pv_disability}


def _round6(value: float) -> float:
    return round(float(value), 6)


def _hash_components(payload: Dict[str, Any]) -> str:
    """Stable integrity hash over the canonical components."""
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _benefit_pct_for(adl_level: int, tables: TableSet, exclude_disability: bool,
                     product: Optional[Product] = None) -> float:
    """Disability benefit percentage used by the kernel.

    When ``Product.fixed_disability_benefit_pct`` is set (e.g. 1.0 for the
    PHINS pure-risk contract which always pays the full L/4 disability sum
    on trigger), that fixed value wins. Otherwise the legacy graded benefit
    table is consulted.
    """
    if exclude_disability:
        return 0.0
    if product is not None and product.fixed_disability_benefit_pct is not None:
        return float(product.fixed_disability_benefit_pct)
    benefit_pct = tables.adl_benefit_pct(adl_level)
    if benefit_pct == 0:
        # The legacy simulator falls back to 0.35 when the ADL benefit table
        # is silent (low-ADL customer who would still receive an average claim).
        return 0.35
    return benefit_pct


def price_policy(
    customer: PricingCustomer,
    product: Product,
    tables: TableSet,
    config: PricingConfig,
    underwriting_loading: float = 0.0,
    exclude_disability: bool = False,
) -> PremiumComponents:
    """Return the canonical :class:`PremiumComponents` for one customer.

    This function is intentionally pure: same inputs always produce the same
    output, including the integrity hash. The kernel never mutates the
    inputs and never reads from a global mutable state.
    """
    coverage = float(customer.coverage)
    term = int(customer.term_years)
    if coverage <= 0 or term <= 0:
        empty = PremiumComponents(
            annual_premium=0.0,
            monthly_premium=0.0,
            risk_premium_annual=0.0,
            mortality_premium_annual=0.0,
            disability_premium_annual=0.0,
            savings_premium_annual=0.0,
            expense_loading_annual=0.0,
            profit_margin_annual=0.0,
            pv_mortality_claims=0.0,
            pv_disability_claims=0.0,
            pv_total_risk_claims=0.0,
            eligible=False,
            decline_reason="invalid_coverage_or_term",
            coverage_amount=coverage,
            term_years=term,
            age=int(customer.age),
            adl_level=int(customer.adl_level),
            product_id=product.id,
            tables_version=tables.version,
            config_version=config.version,
            claim_model=config.claim_model.value,
            savings_formula=config.savings_formula.value,
            savings_rate_used=max(0.0, min(float(product.savings_rate), float(config.savings_rate))),
            savings_yield_used=config.savings_yield_pct,
            age_curve_id=tables.age_curve.id,
        )
        empty.integrity_hash = _hash_components({"empty": True, "product": product.id})
        return empty

    adl = max(1, min(10, int(customer.adl_level)))
    adl_mort_mult = tables.adl_mortality_multiplier(adl)
    adl_dis_mult = tables.adl_disability_multiplier(adl)
    benefit_pct = _benefit_pct_for(adl, tables, exclude_disability, product)
    # Stamp the issue-age band (attained-age schedule still applies inside PV).
    issue_sums = _benefit_sums_for_age(coverage, product, config, int(customer.age))
    resolved_life_share = issue_sums["life_share"]
    resolved_disability_share = issue_sums["disability_share"]
    life_sum_used = issue_sums["life_sum"]
    disability_sum_used = issue_sums["disability_sum"]
    demo = resolve_demographic_rate_factors(customer, config)

    pv_payload = (
        _pv_claims_mutually_exclusive
        if config.claim_model == ClaimModel.MUTUALLY_EXCLUSIVE
        else _pv_claims_independent
    )(
        customer,
        product,
        tables,
        config,
        benefit_pct=benefit_pct,
        exclude_disability=exclude_disability,
        adl_mort_mult=adl_mort_mult,
        adl_dis_mult=adl_dis_mult,
    )
    pv_mortality = pv_payload["pv_mortality"]
    pv_disability = pv_payload["pv_disability"]
    pv_total = pv_mortality + pv_disability

    risk_premium = pv_total / term
    mortality_premium = pv_mortality / term
    disability_premium = pv_disability / term

    # Minimum risk floor for high-ADL with excluded disability (legacy option).
    if config.apply_min_risk_floor and exclude_disability and adl >= 8:
        theoretical = _pv_claims_independent(
            customer,
            product,
            tables,
            config,
            benefit_pct=0.90,
            exclude_disability=False,
            adl_mort_mult=adl_mort_mult,
            adl_dis_mult=adl_dis_mult,
        )
        min_floor = (theoretical["pv_mortality"] + theoretical["pv_disability"] * 0.5) / term
        if risk_premium < min_floor:
            risk_premium = min_floor
            mortality_premium = risk_premium
            disability_premium = 0.0

    if underwriting_loading > 0:
        risk_premium *= 1.0 + float(underwriting_loading)
        mortality_premium *= 1.0 + float(underwriting_loading)
        disability_premium *= 1.0 + float(underwriting_loading)

    savings_premium = _compute_savings_premium(
        coverage, term, product, config, risk_premium_annual=risk_premium,
    )

    if config.expense_basis == "gross_premium":
        # When expense is on gross premium the loading formula becomes:
        # expense = (risk + savings + expense + profit) * pct → solve for expense.
        # For simplicity we use the more common ``expense = risk * pct`` formula.
        expense_loading = (risk_premium + savings_premium) * config.expense_loading_pct
    else:
        expense_loading = risk_premium * config.expense_loading_pct

    if config.profit_basis == "gross_premium":
        profit_margin = (risk_premium + savings_premium + expense_loading) * (
            config.profit_margin_pct / max(1e-9, 1.0 - config.profit_margin_pct)
        )
    else:
        profit_margin = (risk_premium + savings_premium + expense_loading) * config.profit_margin_pct

    annual_premium = risk_premium + savings_premium + expense_loading + profit_margin

    components = PremiumComponents(
        annual_premium=round(annual_premium, 2),
        monthly_premium=round(annual_premium / 12.0, 2),
        risk_premium_annual=round(risk_premium, 2),
        mortality_premium_annual=round(mortality_premium, 2),
        disability_premium_annual=round(disability_premium, 2),
        savings_premium_annual=round(savings_premium, 2),
        expense_loading_annual=round(expense_loading, 2),
        profit_margin_annual=round(profit_margin, 2),
        pv_mortality_claims=round(pv_mortality, 2),
        pv_disability_claims=round(pv_disability, 2),
        pv_total_risk_claims=round(pv_total, 2),
        eligible=True,
        coverage_amount=float(coverage),
        term_years=int(term),
        age=int(customer.age),
        adl_level=int(adl),
        adl_mortality_multiplier=round(adl_mort_mult, 4),
        adl_disability_multiplier=round(adl_dis_mult, 4),
        benefit_pct_used=round(benefit_pct, 4),
        exclude_disability=bool(exclude_disability),
        underwriting_loading=round(float(underwriting_loading), 4),
        age_factor=round(tables.age_curve.factor(int(customer.age)), 4),
        age_curve_id=tables.age_curve.id,
        product_id=product.id,
        tables_version=tables.version,
        config_version=config.version,
        claim_model=config.claim_model.value,
        savings_formula=config.savings_formula.value,
        savings_rate_used=max(0.0, min(float(product.savings_rate), float(config.savings_rate))),
        savings_yield_used=config.savings_yield_pct,
        disability_share_used=round(float(resolved_disability_share), 6),
        disability_sum_used=round(float(disability_sum_used), 2),
        life_share_used=round(float(resolved_life_share), 6),
        life_sum_used=round(float(life_sum_used), 2),
        post_disability_premium_factor=round(
            float(getattr(config, "post_disability_premium_factor", 1.0)), 6
        ),
        post_disability_life_share_of_face=round(
            float(getattr(config, "post_disability_life_share_of_face", 0.75)), 6
        ),
        pre65_disability_continues_policy=bool(
            getattr(config, "pre65_disability_continues_policy", True)
        ),
        post65_claims_mutually_exclusive=bool(
            getattr(config, "post65_claims_mutually_exclusive", True)
        ),
        demographic_mortality_factor=round(float(demo["mortality_factor"]), 6),
        demographic_disability_factor=round(float(demo["disability_factor"]), 6),
        smoking_status_used=demo.get("smoking"),
        gender_used=demo.get("sex"),
        ethnicity_used=demo.get("ethnicity"),
        demographic_factors_applied=dict(demo.get("applied") or {}),
        integrity_checks={
            "components_sum_to_total": abs(
                annual_premium
                - (risk_premium + savings_premium + expense_loading + profit_margin)
            )
            < 1e-6,
            "non_negative_components": all(
                v >= -1e-9
                for v in (
                    risk_premium,
                    savings_premium,
                    expense_loading,
                    profit_margin,
                )
            ),
            "monthly_x_12_equals_annual": abs(round(annual_premium / 12.0, 2) * 12.0 - round(annual_premium, 2))
            < 0.5,
            # When the markup formula is in use, savings_premium MUST equal
            # risk_premium × savings_rate to the cent. This makes the
            # contract intent ("savings_rate is the % of risk premium")
            # verifiable from a single integrity field.
            "savings_markup_identity_holds": (
                config.savings_formula != SavingsFormula.RISK_PREMIUM_MARKUP
                or abs(savings_premium - risk_premium * config.savings_rate) < 1e-6
            ),
            # Mortality PV is bounded by the issue-age life sum (which may be
            # face/4 after the post-65 life step-down), not always full face.
            "pv_mortality_within_coverage_bound": pv_mortality <= max(coverage, life_sum_used) * 1.01,
            # Issue-age bands must match the age-banded schedule
            # (pre-65: life=face & D=life/4; post-65: life=face/4 & D=life).
            "life_share_matches_config": (
                abs(
                    resolved_life_share
                    - _resolve_life_share(product, config, int(customer.age))
                )
                < 1e-9
            ),
            "disability_share_matches_config": (
                abs(
                    resolved_disability_share
                    - _resolve_disability_share(product, config, int(customer.age))
                )
                < 1e-9
            ),
            "disability_share_within_bounds": 0.0 <= resolved_disability_share <= 1.0,
            "life_share_within_bounds": 0.0 <= resolved_life_share <= 1.0,
            "demographic_factors_non_negative": (
                float(demo["mortality_factor"]) >= 0.0
                and float(demo["disability_factor"]) >= 0.0
            ),
        },
    )

    components.integrity_hash = _hash_components(
        {
            "annual": _round6(annual_premium),
            "risk": _round6(risk_premium),
            "savings": _round6(savings_premium),
            "expense": _round6(expense_loading),
            "profit": _round6(profit_margin),
            "pv_mortality": _round6(pv_mortality),
            "pv_disability": _round6(pv_disability),
            "product": product.id,
            "tables_version": tables.version,
            "config_version": config.version,
            "claim_model": config.claim_model.value,
            "savings_formula": config.savings_formula.value,
            "savings_rate": _round6(max(0.0, min(float(product.savings_rate), float(config.savings_rate)))),
            "savings_yield": _round6(config.savings_yield_pct),
            "age": int(customer.age),
            "adl": int(adl),
            "term": int(term),
            "coverage": _round6(coverage),
            "age_curve_id": tables.age_curve.id,
            "underwriting_loading": _round6(underwriting_loading),
            "exclude_disability": bool(exclude_disability),
            "disability_share": _round6(resolved_disability_share),
            "disability_share_pre65": _round6(
                float(config.disability_share_of_life)
                if config.disability_share_of_life is not None
                else float(product.disability_share)
            ),
            "disability_share_post65": (
                None
                if config.disability_share_of_life_post65 is None
                else _round6(float(config.disability_share_of_life_post65))
            ),
            "life_share": _round6(resolved_life_share),
            "life_share_pre65": _round6(float(config.life_share_of_coverage)),
            "life_share_post65": _round6(float(config.life_share_of_coverage_post65)),
            "life_sum": _round6(life_sum_used),
            "disability_sum": _round6(disability_sum_used),
            "disability_band_age": int(getattr(config, "disability_band_age", 65) or 65),
            "pre65_disability_continues_policy": bool(
                getattr(config, "pre65_disability_continues_policy", True)
            ),
            "post_disability_life_share_of_face": _round6(
                float(getattr(config, "post_disability_life_share_of_face", 0.75))
            ),
            "post_disability_premium_factor": _round6(
                float(getattr(config, "post_disability_premium_factor", 1.0))
            ),
            "post65_claims_mutually_exclusive": bool(
                getattr(config, "post65_claims_mutually_exclusive", True)
            ),
            "demographic_mortality_factor": _round6(float(demo["mortality_factor"])),
            "demographic_disability_factor": _round6(float(demo["disability_factor"])),
            "smoking_status": demo.get("smoking"),
            "gender": demo.get("sex"),
            "ethnicity": demo.get("ethnicity"),
            "demographic_factors_applied": demo.get("applied") or {},
            "smoker_mortality_factor": _round6(float(config.smoker_mortality_factor)),
            "smoker_disability_factor": _round6(float(config.smoker_disability_factor)),
            "former_smoker_mortality_factor": _round6(float(config.former_smoker_mortality_factor)),
            "former_smoker_disability_factor": _round6(float(config.former_smoker_disability_factor)),
            "nonsmoker_mortality_factor": _round6(float(config.nonsmoker_mortality_factor)),
            "nonsmoker_disability_factor": _round6(float(config.nonsmoker_disability_factor)),
            "male_mortality_factor": _round6(float(config.male_mortality_factor)),
            "male_disability_factor": _round6(float(config.male_disability_factor)),
            "female_mortality_factor": _round6(float(config.female_mortality_factor)),
            "female_disability_factor": _round6(float(config.female_disability_factor)),
            "ethnicity_mortality_factors": {
                str(k): _round6(float(v))
                for k, v in sorted((config.ethnicity_mortality_factors or {}).items())
            },
            "ethnicity_disability_factors": {
                str(k): _round6(float(v))
                for k, v in sorted((config.ethnicity_disability_factors or {}).items())
            },
        }
    )
    return components


# =============================================================================
# CONVENIENCE: build a TableSet from the central ActuarialTablesStore
# =============================================================================

def table_set_from_store(store: Any, age_curve_id: str = "identity",
                         cohort_overrides: Optional[Dict[str, Dict[str, List[Dict[str, Any]]]]] = None,
                         ) -> TableSet:
    """Snapshot the central :class:`ActuarialTablesStore` into a :class:`TableSet`.

    The kernel cannot import ``services.actuarial_service`` at module load time
    (circular import) so the conversion is done lazily via this helper.
    """
    tables = store.get_current_tables()
    return TableSet(
        mortality_rates=list(tables.get("mortality_rates", [])),
        disability_incidence_rates=list(tables.get("disability_incidence_rates", [])),
        adl_mortality_multipliers=list(tables.get("adl_mortality_multipliers", [])),
        adl_disability_multipliers=list(tables.get("adl_disability_multipliers", [])),
        adl_benefit_percentages=list(tables.get("adl_benefit_percentages", [])),
        lapse_rates=list(tables.get("lapse_rates", [])),
        age_curve=get_age_curve(age_curve_id),
        version=getattr(store, "current_version", "central_v2"),
        cohort_overrides=cohort_overrides or {},
    )


def pricing_config_from_underwriting(uw_config: Any,
                                     savings_rate: Optional[float] = None,
                                     savings_yield_pct: Optional[float] = None,
                                     claim_model: ClaimModel = ClaimModel.MUTUALLY_EXCLUSIVE,
                                     apply_lapse_adjustment: bool = False,
                                     apply_min_risk_floor: bool = False,
                                     savings_formula: SavingsFormula = SavingsFormula.STRAIGHT_LINE,
                                     disability_share_of_life: Optional[float] = None,
                                     disability_share_of_life_post65: Optional[float] = None,
                                     life_share_of_coverage: Optional[float] = None,
                                     life_share_of_coverage_post65: Optional[float] = None,
                                     disability_band_age: Optional[int] = None,
                                     ) -> PricingConfig:
    """Build a :class:`PricingConfig` from an existing :class:`UnderwritingConfig`.

    Age-banded life and D/life shares flow from UnderwritingConfig by default
    (pre-65: life=face & D=life/4; post-65: life=face/4 & D=life).
    """
    resolved_share = disability_share_of_life
    if resolved_share is None:
        resolved_share = getattr(uw_config, "disability_share_of_life", 0.25)
    resolved_post = disability_share_of_life_post65
    if resolved_post is None and not hasattr(uw_config, "disability_share_of_life_post65"):
        resolved_post = 1.0
    elif resolved_post is None:
        resolved_post = getattr(uw_config, "disability_share_of_life_post65", 1.0)
    resolved_life = life_share_of_coverage
    if resolved_life is None:
        resolved_life = getattr(uw_config, "life_share_of_coverage", 1.0)
    resolved_life_post = life_share_of_coverage_post65
    if resolved_life_post is None:
        resolved_life_post = getattr(uw_config, "life_share_of_coverage_post65", 0.25)
    band = disability_band_age
    if band is None:
        band = int(getattr(uw_config, "disability_band_age", 65) or 65)
    cfg_version = str(getattr(uw_config, "config_version", None) or "kernel_v1")

    def _f(name: str, default: float = 1.0) -> float:
        return float(getattr(uw_config, name, default))

    def _eth_map(name: str) -> Dict[str, float]:
        raw = getattr(uw_config, name, None) or {}
        out = {
            "caucasian": 1.0,
            "african": 1.0,
            "hispanic": 1.0,
            "asian": 1.0,
            "other": 1.0,
        }
        for k, v in dict(raw).items():
            out[str(k).lower()] = float(v)
        return out

    return PricingConfig(
        expense_loading_pct=float(getattr(uw_config, "expense_loading_pct", 0.15)),
        profit_margin_pct=float(getattr(uw_config, "profit_margin_pct", 0.10)),
        discount_rate=float(getattr(uw_config, "discount_rate", 0.035)),
        savings_rate=0.5 if savings_rate is None else float(savings_rate),
        savings_yield_pct=0.0 if savings_yield_pct is None else float(savings_yield_pct),
        savings_formula=savings_formula,
        claim_model=claim_model,
        apply_lapse_adjustment=apply_lapse_adjustment,
        apply_min_risk_floor=apply_min_risk_floor,
        disability_share_of_life=(
            float(resolved_share) if resolved_share is not None else None
        ),
        disability_share_of_life_post65=(
            None if resolved_post is None else float(resolved_post)
        ),
        life_share_of_coverage=float(resolved_life),
        life_share_of_coverage_post65=float(resolved_life_post),
        disability_band_age=int(band),
        pre65_disability_continues_policy=bool(
            getattr(uw_config, "pre65_disability_continues_policy", True)
        ),
        post_disability_life_share_of_face=max(
            0.0, min(1.0, float(getattr(uw_config, "post_disability_life_share_of_face", 0.75)))
        ),
        post_disability_premium_factor=max(
            0.0, min(5.0, float(getattr(uw_config, "post_disability_premium_factor", 1.0)))
        ),
        post65_claims_mutually_exclusive=bool(
            getattr(uw_config, "post65_claims_mutually_exclusive", True)
        ),
        smoker_mortality_factor=_f("smoker_mortality_factor"),
        smoker_disability_factor=_f("smoker_disability_factor"),
        former_smoker_mortality_factor=_f("former_smoker_mortality_factor"),
        former_smoker_disability_factor=_f("former_smoker_disability_factor"),
        nonsmoker_mortality_factor=_f("nonsmoker_mortality_factor"),
        nonsmoker_disability_factor=_f("nonsmoker_disability_factor"),
        male_mortality_factor=_f("male_mortality_factor"),
        male_disability_factor=_f("male_disability_factor"),
        female_mortality_factor=_f("female_mortality_factor"),
        female_disability_factor=_f("female_disability_factor"),
        ethnicity_mortality_factors=_eth_map("ethnicity_mortality_factors"),
        ethnicity_disability_factors=_eth_map("ethnicity_disability_factors"),
        version=cfg_version,
    )


__all__ = [
    "AgeCurve",
    "AGE_CURVE_REGISTRY",
    "ClaimModel",
    "PRODUCT_REGISTRY",
    "PremiumComponents",
    "PricingConfig",
    "PricingCustomer",
    "Product",
    "SavingsFormula",
    "TableSet",
    "get_age_curve",
    "get_product",
    "price_policy",
    "pricing_config_from_underwriting",
    "register_age_curve",
    "register_product",
    "resolve_demographic_rate_factors",
    "risk_reference_v1_factor",
    "table_set_from_store",
]
