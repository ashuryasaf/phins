"""
PHINS Monte Carlo Methodology Evaluation
========================================

Read-only stochastic evaluation of the platform's *own* decision rules and
assumptions. It answers "how well would PHINS's rules perform under a
transparent, adjustable generative world?" for six surfaces:

- ``risk``          the shared underwriting scorer
                    (``services.underwriting_risk_scoring.score_risk_inputs``)
- ``underwriting``  ADL decline / loading / coverage-cap rules and the
                    auto-approval gates (``UnderwritingConfig``), priced by
                    the canonical pricing kernel
- ``actuarial``     mortality / disability tables, loss ratio, the 150%
                    reserve rule, IBNR factors, lapse and anti-selection
- ``claims``        claims-bot authenticity weights and triage thresholds
                    (``ClaimsBotService``)
- ``sales``         the BI compound-MRR forecast (5%/month default)
- ``ai``            advisory-LLM dispositions (``review_disposition``) and
                    the AI underwriting automation thresholds

Data-integrity contract
-----------------------
* **Pure and read-only.** Nothing here writes to a store, the database, a
  ledger, a snapshot file or an audit log. PHINS assumptions are *read* from
  the live configuration objects and snapshotted into the result.
* **Deterministic.** All randomness comes from one ``random.Random(seed)``;
  the same seed and parameters always yield the same ``results_sha256``.
* **Synthetic by default.** Populations are generated, never taken from
  customer records. Optional ``observed`` dicts (policies/claims) are read
  only for aggregate calibration (counts, MRR); they are fingerprinted
  before and after the run and the run reports ``observed_inputs_unchanged``.
* **Explicit world model.** Every "truth" assumption that is *not* a PHINS
  assumption lives in :class:`WorldAssumptions`, is documented, adjustable,
  and hashed into the result so findings can never be mistaken for facts.

Design note: prompts may explain, rules decide (see
``docs/ai_surface_design_principles.md``). This module is diagnostic BI — it
recommends, it never changes a threshold.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import math
import os
import random
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ENGINE_VERSION = "mc-eval-1.0.0"

ALL_MODULES: Tuple[str, ...] = (
    "risk", "underwriting", "actuarial", "claims", "sales", "ai",
)

# Hard caps so the HTTP surface cannot be used to burn CPU.
MAX_LIVES = 50_000
MAX_TRIALS = 20_000
MAX_BOOTSTRAP = 2_000
MAX_HORIZON_YEARS = 30


# ─────────────────────────────────────────────────────────────────────────────
# Parameters
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class WorldAssumptions:
    """Generative "truth" used to score PHINS rules. NOT PHINS configuration.

    Relative risks are deliberately conservative literature-style
    magnitudes; they exist so the evaluation can measure how PHINS behaves
    when the world differs from its neutral (1.0) demographic factors.
    """

    # Excess hazard the world applies that PHINS prices at 1.0 by default.
    smoker_mortality_rr: float = 2.0
    smoker_disability_rr: float = 1.4
    former_smoker_mortality_rr: float = 1.3
    former_smoker_disability_rr: float = 1.15
    # Hazard multiplier = 1 + condition_hazard_scale × Σ scorer risk_impact
    condition_hazard_scale: float = 2.5
    bmi_hazard_per_point_over_30: float = 0.03
    prior_claim_hazard_rr: float = 1.15
    # Claim reporting lag (lognormal) used to test IBNR factors.
    reporting_lag_mean_days: float = 45.0
    reporting_lag_sigma: float = 0.8
    # Anti-selection stress: healthy lives lapse more, impaired lives less.
    antiselection_low_hazard_lapse_mult: float = 1.3
    antiselection_high_hazard_lapse_mult: float = 0.7
    # Claims triage world.
    fraud_rate: float = 0.05
    contestability_share: float = 0.40
    # Sales world (PHINS default growth is the mean; volatility is the world).
    monthly_growth_sd: float = 0.04
    growth_autocorrelation: float = 0.30
    shock_probability_monthly: float = 0.03
    shock_magnitude: float = -0.15
    # AI world.
    ai_accuracy: float = 0.85
    ai_error_cost_units: float = 50.0
    ai_review_cost_units: float = 1.0
    uw_bad_applicant_rate: float = 0.15


@dataclass
class EvaluationParams:
    seed: int = 20260911
    lives: int = 2_000
    trials: int = 400
    horizon_years: int = 5
    bootstrap_samples: int = 200
    modules: Tuple[str, ...] = ALL_MODULES
    world: WorldAssumptions = field(default_factory=WorldAssumptions)

    def normalized(self) -> "EvaluationParams":
        mods = tuple(m for m in ALL_MODULES if m in set(self.modules or ALL_MODULES))
        return EvaluationParams(
            seed=int(self.seed),
            lives=max(50, min(MAX_LIVES, int(self.lives))),
            trials=max(20, min(MAX_TRIALS, int(self.trials))),
            horizon_years=max(1, min(MAX_HORIZON_YEARS, int(self.horizon_years))),
            bootstrap_samples=max(0, min(MAX_BOOTSTRAP, int(self.bootstrap_samples))),
            modules=mods or ALL_MODULES,
            world=self.world,
        )


def params_from_query(params: Optional[Dict[str, Any]]) -> EvaluationParams:
    """Coerce flat (string) query parameters into :class:`EvaluationParams`."""
    params = params or {}

    def _int(name: str, default: int) -> int:
        try:
            return int(float(params.get(name, default)))
        except (TypeError, ValueError):
            return default

    modules_raw = str(params.get("modules") or "").strip()
    modules = tuple(m.strip() for m in modules_raw.split(",") if m.strip()) or ALL_MODULES

    world = WorldAssumptions()
    for f in fields(WorldAssumptions):
        raw = params.get(f"world.{f.name}")
        if raw is None:
            continue
        try:
            setattr(world, f.name, float(raw))
        except (TypeError, ValueError):
            pass

    return EvaluationParams(
        seed=_int("seed", 20260911),
        lives=_int("lives", 2_000),
        trials=_int("trials", 400),
        horizon_years=_int("horizon_years", 5),
        bootstrap_samples=_int("bootstrap", 200),
        modules=modules,
        world=world,
    ).normalized()


# ─────────────────────────────────────────────────────────────────────────────
# Small statistics toolkit (pure Python; numpy is not a PHINS dependency)
# ─────────────────────────────────────────────────────────────────────────────

def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _stdev(xs: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def _percentile(sorted_xs: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile on an already sorted sequence."""
    if not sorted_xs:
        return 0.0
    if len(sorted_xs) == 1:
        return float(sorted_xs[0])
    pos = (len(sorted_xs) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(sorted_xs) - 1)
    frac = pos - lo
    return float(sorted_xs[lo] + (sorted_xs[hi] - sorted_xs[lo]) * frac)


def _distribution(xs: Sequence[float]) -> Dict[str, float]:
    s = sorted(xs)
    if not s:
        return {"n": 0}
    p95 = _percentile(s, 0.95)
    p99 = _percentile(s, 0.99)
    tail99 = [x for x in s if x >= p99] or [s[-1]]
    return {
        "n": len(s),
        "mean": round(_mean(s), 6),
        "stdev": round(_stdev(s), 6),
        "min": round(s[0], 6),
        "p05": round(_percentile(s, 0.05), 6),
        "p25": round(_percentile(s, 0.25), 6),
        "p50": round(_percentile(s, 0.50), 6),
        "p75": round(_percentile(s, 0.75), 6),
        "p95": round(p95, 6),
        "p99": round(p99, 6),
        "max": round(s[-1], 6),
        "var_95": round(p95, 6),
        "var_99": round(p99, 6),
        "tvar_99": round(_mean(tail99), 6),
    }


def wilson_interval(successes: int, n: int, z: float = 1.959964) -> Tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (centre - half) / denom), min(1.0, (centre + half) / denom))


def _ranks(xs: Sequence[float]) -> List[float]:
    """Average ranks (1-based) with tie handling."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def auc_score(scores: Sequence[float], labels: Sequence[int]) -> Optional[float]:
    """Mann–Whitney AUC; ``None`` when a class is empty."""
    pos = sum(1 for y in labels if y)
    neg = len(labels) - pos
    if pos == 0 or neg == 0:
        return None
    ranks = _ranks(scores)
    rank_sum_pos = sum(r for r, y in zip(ranks, labels) if y)
    return (rank_sum_pos - pos * (pos + 1) / 2) / (pos * neg)


def spearman(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    if len(xs) < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = _mean(rx), _mean(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx <= 0 or vy <= 0:
        return None
    return cov / math.sqrt(vx * vy)


def brier_score(probs: Sequence[float], labels: Sequence[int]) -> float:
    if not probs:
        return 0.0
    return sum((p - y) ** 2 for p, y in zip(probs, labels)) / len(probs)


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 50:
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    limit = math.exp(-lam)
    k, prod = 0, rng.random()
    while prod > limit:
        k += 1
        prod *= rng.random()
    return k


def _binomial(rng: random.Random, n: int, p: float) -> int:
    """Exact inversion for small n·p, normal approximation for large cells."""
    if n <= 0 or p <= 0:
        return 0
    if p >= 1:
        return n
    mean = n * p
    if mean > 60 and n * (1 - p) > 60:
        return max(0, min(n, int(round(rng.gauss(mean, math.sqrt(mean * (1 - p)))))))
    if n <= 32:
        return sum(1 for _ in range(n) if rng.random() < p)
    # Sequential inversion of the CDF.
    u = rng.random()
    q = 1 - p
    pk = q ** n
    cdf = pk
    k = 0
    while u > cdf and k < n:
        pk *= (n - k) / (k + 1) * p / q
        k += 1
        cdf += pk
    return k


def _sha256_of(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _r(x: Optional[float], nd: int = 4) -> Optional[float]:
    return None if x is None else round(float(x), nd)


# ─────────────────────────────────────────────────────────────────────────────
# PHINS assumption snapshot (read-only)
# ─────────────────────────────────────────────────────────────────────────────

_CONDITION_CATALOG: Tuple[Tuple[str, float, float], ...] = (
    # (condition text understood by parse_conditions_text, base prevalence at 25, slope per year)
    ("hypertension", 0.040, 0.0060),
    ("high cholesterol", 0.030, 0.0050),
    ("type 2 diabetes", 0.015, 0.0040),
    ("asthma", 0.050, 0.0000),
    ("depression", 0.060, 0.0000),
    ("thyroid disorder", 0.020, 0.0010),
    ("heart disease", 0.004, 0.0030),
    ("cancer", 0.002, 0.0020),
)


def _load_phins_context() -> Dict[str, Any]:
    """Resolve the live PHINS rule objects once per run (read-only)."""
    from services import actuarial_service as act
    from services import pricing_kernel as pk
    from services.underwriting_risk_scoring import ENGINE_VERSION as UW_ENGINE
    from services.claims_bot_service import ClaimsBotService
    from services.ai_threshold_config import (
        DEFAULT_APPROVE_THRESHOLD, DEFAULT_REJECT_THRESHOLD,
    )

    store = act.get_actuarial_store()
    cfg = store.config
    tables = store.get_current_tables()
    reserve_cfg = act.ReserveConfig()

    accept = float(os.environ.get("PHINS_AI_ACCEPT_THRESHOLD", "0.90"))
    review = float(os.environ.get("PHINS_AI_REVIEW_THRESHOLD", "0.70"))
    try:
        from services.assessment_ai_service import _MAX_ADVISORY_CONFIDENCE  # type: ignore
        advisory_cap = float(_MAX_ADVISORY_CONFIDENCE)
    except Exception:
        advisory_cap = None

    pricing_config = pk.pricing_config_from_underwriting(
        cfg,
        savings_rate=0.0,
        savings_yield_pct=0.0,
        claim_model=pk.ClaimModel.MUTUALLY_EXCLUSIVE,
        savings_formula=pk.SavingsFormula.RISK_PREMIUM_MARKUP,
    )
    product = pk.get_product("phins_pure_risk_adjustable")
    table_set = pk.table_set_from_store(
        store, age_curve_id="identity",
        cohort_overrides=act.get_cohort_overrides_snapshot(),
    )

    assumptions = {
        "tables_version": store.current_version,
        "mortality_rates": tables.get("mortality_rates"),
        "disability_incidence_rates": tables.get("disability_incidence_rates"),
        "adl_mortality_multipliers": tables.get("adl_mortality_multipliers"),
        "adl_disability_multipliers": tables.get("adl_disability_multipliers"),
        "adl_benefit_percentages": tables.get("adl_benefit_percentages"),
        "lapse_rates": tables.get("lapse_rates"),
        "underwriting_config": store.public_config_dict(),
        "underwriting_scorer_engine": UW_ENGINE,
        "underwriting_scorer_bands": {
            "very_low": "<=0.15 auto_approve", "low": "<=0.25 approve_standard",
            "moderate": "<=0.40 loading 15%+", "elevated": "<=0.55 loading 30%+ exclusions",
            "high": "<=0.70 refer_senior_uw 50%+", "very_high": ">0.70 decline",
        },
        "automation_base_rates": act.AutomationMetrics.BASE_RATES,
        "reserve_requirement_multiple": 1.5,
        "reserve_config": asdict(reserve_cfg),
        "reserves_reporting": {"loss_ratio_assumption": 0.65, "ibnr_factor_of_premium": 0.15},
        "reinsurance_bands": {"very_high": ">=95", "high": ">=75", "medium": ">=45", "low": "<45"},
        "claims_bot": {
            "score_weights": ClaimsBotService.SCORE_WEIGHTS,
            "contestability_years": ClaimsBotService.CONTESTABILITY_PERIOD_YEARS,
            "approve_full_threshold": 0.85,
            "approve_partial_threshold": 0.70,
            "deny_threshold": 0.45,
            "fraud_penalty_per_severity": 0.1,
            "hidden_condition_penalty": 0.3,
        },
        "bi_revenue_forecast": {"monthly_growth_default": 0.05, "months_ahead_default": 12,
                                "churn_modelled": False},
        "ai_review_disposition": {"accept": accept, "review": review,
                                  "advisory_confidence_cap": advisory_cap},
        "ai_underwriting_thresholds": {"approve": DEFAULT_APPROVE_THRESHOLD,
                                       "reject": DEFAULT_REJECT_THRESHOLD},
    }
    provenance = [
        {"assumption": "mortality/disability/ADL/lapse tables", "source": "services/actuarial_service.py:ActuarialTablesStore"},
        {"assumption": "ADL decline, loadings, coverage caps, auto-approval gates", "source": "services/actuarial_service.py:UnderwritingConfig"},
        {"assumption": "risk score weights and bands", "source": "services/underwriting_risk_scoring.py:score_risk_inputs"},
        {"assumption": "condition loadings", "source": "services/chat_application_service.py:_CONDITION_KEYWORDS"},
        {"assumption": "premium decomposition", "source": "services/pricing_kernel.py:price_policy"},
        {"assumption": "reserve requirement 150%, automation base rates", "source": "services/actuarial_service.py:PortfolioSimulator/AutomationMetrics"},
        {"assumption": "IBNR 10% of claims", "source": "services/actuarial_service.py:ReserveConfig"},
        {"assumption": "IBNR = premium × 65% × 15%", "source": "services/reserves_reporting_service.py"},
        {"assumption": "claims authenticity weights/thresholds", "source": "services/claims_bot_service.py:ClaimsBotService"},
        {"assumption": "5%/month MRR growth", "source": "services/bi_analytics_service.py:predict_revenue_forecast"},
        {"assumption": "AI accept/review thresholds", "source": "services/llm_providers.py:review_disposition"},
        {"assumption": "AI underwriting approve/reject thresholds", "source": "services/ai_threshold_config.py"},
    ]
    return {
        "act": act, "pk": pk, "store": store, "cfg": cfg, "reserve_cfg": reserve_cfg,
        "pricing_config": pricing_config, "product": product, "table_set": table_set,
        "assumptions": assumptions, "provenance": provenance,
        "ai_accept": accept, "ai_review": review, "advisory_cap": advisory_cap,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic population
# ─────────────────────────────────────────────────────────────────────────────

_ADL_WEIGHTS_BY_AGE = (
    (26, [70, 15, 8, 4, 2, 1, 0, 0, 0, 0]),
    (46, [50, 20, 15, 8, 4, 2, 1, 0, 0, 0]),
    (200, [30, 20, 20, 15, 8, 4, 2, 1, 0, 0]),
)


def _adl_for_age(rng: random.Random, age: int) -> int:
    for limit, weights in _ADL_WEIGHTS_BY_AGE:
        if age < limit:
            return rng.choices(range(1, 11), weights=weights)[0]
    return 1


def _generate_population(rng: random.Random, n: int, ctx: Dict[str, Any],
                         world: WorldAssumptions) -> List[Dict[str, Any]]:
    """Synthetic adult applicants with PHINS-facing inputs and world hazards."""
    from services.chat_application_service import parse_conditions_text

    store = ctx["store"]
    cfg = ctx["cfg"]
    act = ctx["act"]
    lives: List[Dict[str, Any]] = []
    for idx in range(n):
        age = int(max(18, min(75, round(rng.gauss(35.0, 12.0)))))
        u = rng.random()
        smoking = "current" if u < 0.15 else "former" if u < 0.25 else "never"
        gender = "male" if rng.random() < 0.49 else "female"
        adl = _adl_for_age(rng, age)
        bmi = round(max(16.0, min(50.0, rng.gauss(26.5, 4.5))), 1)
        conditions: List[Dict[str, Any]] = []
        for name, base, slope in _CONDITION_CATALOG:
            prevalence = base + slope * max(0, age - 25)
            if rng.random() < prevalence:
                conditions.extend(parse_conditions_text(name))
        claims_count = _poisson(rng, 0.25)
        coverage = float(max(50_000.0, min(2_000_000.0, rng.lognormvariate(math.log(250_000.0), 0.6))))
        term = rng.randint(5, 30)

        risk_impact_sum = sum(float(c.get("risk_impact", 0.0)) for c in conditions)
        cond_mult = 1.0 + world.condition_hazard_scale * risk_impact_sum
        bmi_mult = 1.0 + world.bmi_hazard_per_point_over_30 * max(0.0, bmi - 30.0)
        claims_mult = world.prior_claim_hazard_rr ** claims_count
        if smoking == "current":
            smoke_m, smoke_d = world.smoker_mortality_rr, world.smoker_disability_rr
        elif smoking == "former":
            smoke_m, smoke_d = world.former_smoker_mortality_rr, world.former_smoker_disability_rr
        else:
            smoke_m, smoke_d = 1.0, 1.0

        q = store.get_mortality_rate(age) * store.get_adl_mortality_multiplier(adl)
        i = store.get_disability_rate(age) * store.get_adl_disability_multiplier(adl)
        q_true = min(0.5, q * smoke_m * cond_mult * bmi_mult * claims_mult)
        i_true = min(0.5, i * smoke_d * cond_mult * bmi_mult)

        sums = act.contract_benefit_sums_from_config(coverage, age, cfg)
        lives.append({
            "idx": idx, "age": age, "gender": gender, "smoking_status": smoking,
            "adl": adl, "bmi": bmi, "conditions": conditions,
            "claims_count": claims_count, "coverage": coverage, "term": term,
            "q_phins": q, "i_phins": i, "q_true": q_true, "i_true": i_true,
            "life_sum": sums["life_sum"], "disability_sum": sums["disability_sum"],
            "benefit_pct": store.get_adl_benefit_pct(adl),
        })
    return lives


def _annual_claim_probability(life: Dict[str, Any], truth: bool = True) -> float:
    q = life["q_true"] if truth else life["q_phins"]
    i = life["i_true"] if truth else life["i_phins"]
    return q + (1 - q) * i


def _expected_annual_loss(life: Dict[str, Any], truth: bool = True,
                          exclude_disability: bool = False) -> float:
    q = life["q_true"] if truth else life["q_phins"]
    i = life["i_true"] if truth else life["i_phins"]
    dis = 0.0 if exclude_disability else i * (1 - q) * life["benefit_pct"] * life["disability_sum"]
    return q * life["life_sum"] + dis


# ─────────────────────────────────────────────────────────────────────────────
# Module 1 — risk assessment scorer
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_risk_assessment(rng: random.Random, lives: List[Dict[str, Any]],
                             params: EvaluationParams, ctx: Dict[str, Any]) -> Dict[str, Any]:
    from services.underwriting_risk_scoring import assess_application

    H = params.horizon_years
    scores, labels, hazards, categories, recs, adjustments = [], [], [], [], [], []
    for life in lives:
        # Same extraction + scoring path production uses for an application
        # record (adds ADL-impairment / obesity conditions exactly as it would).
        result = assess_application({
            "age": life["age"], "smoking_status": life["smoking_status"],
            "bmi": life["bmi"], "adl_level": life["adl"],
            "medical_conditions": life["conditions"],
        }, claims_count=life["claims_count"])
        if result.get("overall_risk") is None:
            raise RuntimeError(f"underwriting scorer failed: {result.get('error')}")
        p_annual = _annual_claim_probability(life, truth=True)
        p_horizon = 1 - (1 - p_annual) ** H
        y = 1 if rng.random() < p_horizon else 0
        scores.append(float(result["overall_risk"]))
        labels.append(y)
        hazards.append(p_annual)
        categories.append(result["risk_category"])
        recs.append(result["recommendation_type"])
        adjustments.append(float(result.get("premium_adjustment") or 0.0))
        life["uw_score"] = float(result["overall_risk"])
        life["uw_category"] = result["risk_category"]
        life["uw_recommendation"] = result["recommendation_type"]
        life["uw_premium_adjustment"] = float(result.get("premium_adjustment") or 0.0)
        life["horizon_claim"] = y

    auc = auc_score(scores, labels)
    oracle_auc = auc_score(hazards, labels)

    boot_aucs: List[float] = []
    n = len(lives)
    for _ in range(params.bootstrap_samples):
        idx = [rng.randrange(n) for _ in range(n)]
        a = auc_score([scores[i] for i in idx], [labels[i] for i in idx])
        if a is not None:
            boot_aucs.append(a)
    boot_sorted = sorted(boot_aucs)

    band_order = ["very_low", "low", "moderate", "elevated", "high", "very_high"]
    calibration = []
    ref_loss = None
    for band in band_order:
        members = [k for k, c in enumerate(categories) if c == band]
        if not members:
            continue
        claims = sum(labels[k] for k in members)
        lo, hi = wilson_interval(claims, len(members))
        mean_loss = _mean([_expected_annual_loss(lives[k]) for k in members])
        mean_prem_base = _mean([_expected_annual_loss(lives[k], truth=False) for k in members])
        if band == "low" and ref_loss is None:
            ref_loss = mean_loss
        calibration.append({
            "band": band, "n": len(members), "share": round(len(members) / n, 4),
            "mean_score": _r(_mean([scores[k] for k in members])),
            "observed_claim_rate": _r(claims / len(members)),
            "observed_ci95": [_r(lo), _r(hi)],
            "mean_true_annual_hazard": _r(_mean([hazards[k] for k in members]), 6),
            "mean_true_expected_annual_loss": round(mean_loss, 2),
            "mean_phins_table_expected_annual_loss": round(mean_prem_base, 2),
            "applied_premium_adjustment_mean": _r(_mean([adjustments[k] for k in members])),
        })
    # Loading adequacy: does the applied loading cover the excess of *true*
    # expected loss over what the neutral PHINS tables already price?
    for row in calibration:
        base = row["mean_phins_table_expected_annual_loss"]
        excess = (row["mean_true_expected_annual_loss"] / base - 1.0) if base > 0 else None
        row["required_loading_vs_tables"] = _r(excess)
        # Declined lives are never priced, so a loading gap is meaningless there.
        if excess is None or row["band"] == "very_high":
            row["loading_gap"] = None
        else:
            row["loading_gap"] = _r((row["applied_premium_adjustment_mean"] or 0.0) - excess)

    # Monotonicity is judged only on bands large enough to have a stable rate.
    observed_rates = [row["observed_claim_rate"] for row in calibration if row["n"] >= 30]
    monotone = all(a <= b + 1e-12 for a, b in zip(observed_rates, observed_rates[1:]))

    rec_mix = {}
    for r in recs:
        rec_mix[r] = rec_mix.get(r, 0) + 1
    rec_mix = {k: round(v / n, 4) for k, v in sorted(rec_mix.items())}
    base_rates = ctx["assumptions"]["automation_base_rates"]["underwriting"]

    return {
        "lives": n, "horizon_years": H,
        "positives": sum(labels), "base_rate": _r(sum(labels) / n),
        "auc": _r(auc), "auc_bootstrap_ci95": [_r(_percentile(boot_sorted, 0.025)),
                                                _r(_percentile(boot_sorted, 0.975))] if boot_sorted else None,
        "oracle_auc_true_hazard": _r(oracle_auc),
        "auc_gap_to_oracle": _r((oracle_auc or 0) - (auc or 0)),
        "spearman_score_vs_true_hazard": _r(spearman(scores, hazards)),
        "brier_score_raw": _r(brier_score(scores, labels)),
        "brier_score_base_rate": _r(brier_score([sum(labels) / n] * n, labels)),
        "score_is_probability": False,
        "calibration_by_band": calibration,
        "band_monotonic_in_outcomes": monotone,
        "recommendation_mix": rec_mix,
        "assumed_automation_mix": base_rates,
        "auto_approve_share_vs_assumed": _r(rec_mix.get("auto_approve", 0.0) - base_rates["auto_approve"]),
        "decline_share_vs_assumed": _r(rec_mix.get("decline", 0.0) - base_rates["auto_decline"]),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Module 2 — underwriting rules + pricing kernel
# ─────────────────────────────────────────────────────────────────────────────

def _price_life(life: Dict[str, Any], ctx: Dict[str, Any], loading: float,
                exclude_disability: bool) -> Any:
    pk = ctx["pk"]
    return pk.price_policy(
        pk.PricingCustomer(
            age=life["age"], coverage=life["coverage"], term_years=life["term"],
            adl_level=life["adl"], gender=life["gender"],
            smoking_status=life["smoking_status"], ethnicity=None,
        ),
        ctx["product"], ctx["table_set"], ctx["pricing_config"],
        underwriting_loading=loading, exclude_disability=exclude_disability,
    )


def _scaled_life(life: Dict[str, Any], coverage: float) -> Dict[str, Any]:
    """Copy of ``life`` with coverage (and the derived benefit sums) rescaled."""
    scaled = dict(life)
    scale = coverage / life["coverage"] if life["coverage"] else 1.0
    scaled["coverage"] = coverage
    scaled["life_sum"] = life["life_sum"] * scale
    scaled["disability_sum"] = life["disability_sum"] * scale
    return scaled


def _apply_uw_rules(life: Dict[str, Any], cfg: Any, decline_threshold: int) -> Dict[str, Any]:
    adl = life["adl"]
    if adl >= decline_threshold:
        return {"eligible": False, "loading": 0.0, "exclude_disability": False,
                "coverage": life["coverage"], "capped": False}
    coverage = life["coverage"]
    capped = False
    limits = {int(k): float(v) for k, v in dict(cfg.coverage_limits or {}).items()}
    if adl in limits and coverage > limits[adl]:
        coverage, capped = limits[adl], True
    loadings = {int(k): float(v) for k, v in dict(cfg.loadings or {}).items()}
    return {"eligible": True, "loading": loadings.get(adl, 0.0),
            "exclude_disability": adl >= int(cfg.disability_exclusion_threshold),
            "coverage": coverage, "capped": capped}


def evaluate_underwriting_rules(rng: random.Random, lives: List[Dict[str, Any]],
                                params: EvaluationParams, ctx: Dict[str, Any]) -> Dict[str, Any]:
    cfg = ctx["cfg"]
    act = ctx["act"]
    n = len(lives)

    priced = 0
    declined = 0
    capped = 0
    excluded = 0
    by_adl: Dict[int, Dict[str, float]] = {}
    by_smoking: Dict[str, Dict[str, float]] = {}
    total_premium = 0.0
    total_true_loss = 0.0
    total_phins_loss = 0.0
    for life in lives:
        rule = _apply_uw_rules(life, cfg, int(cfg.decline_threshold))
        life["uw_rule"] = rule
        if not rule["eligible"]:
            declined += 1
            life["premium"] = 0.0
            continue
        scaled = _scaled_life(life, rule["coverage"])
        comp = _price_life(scaled, ctx, rule["loading"], rule["exclude_disability"])
        premium = float(comp.annual_premium)
        risk_premium = float(comp.risk_premium_annual)
        life["premium"] = premium
        life["risk_premium"] = risk_premium
        life["pv_total_risk_claims"] = float(comp.pv_total_risk_claims)
        life["exclude_disability"] = rule["exclude_disability"]
        life["coverage"] = scaled["coverage"]
        life["life_sum"] = scaled["life_sum"]
        life["disability_sum"] = scaled["disability_sum"]
        true_loss = _expected_annual_loss(life, truth=True, exclude_disability=rule["exclude_disability"])
        phins_loss = _expected_annual_loss(life, truth=False, exclude_disability=rule["exclude_disability"])
        life["true_expected_loss"] = true_loss
        life["phins_expected_loss"] = phins_loss
        priced += 1
        capped += int(rule["capped"])
        excluded += int(rule["exclude_disability"])
        total_premium += premium
        total_true_loss += true_loss
        total_phins_loss += phins_loss
        cell = by_adl.setdefault(life["adl"], {"n": 0, "premium": 0.0, "true_loss": 0.0, "phins_loss": 0.0})
        cell["n"] += 1
        cell["premium"] += premium
        cell["true_loss"] += true_loss
        cell["phins_loss"] += phins_loss
        scell = by_smoking.setdefault(life["smoking_status"], {"n": 0, "premium": 0.0, "true_loss": 0.0, "phins_loss": 0.0})
        scell["n"] += 1
        scell["premium"] += premium
        scell["true_loss"] += true_loss
        scell["phins_loss"] += phins_loss

    def _lr_rows(cells: Dict[Any, Dict[str, float]]) -> List[Dict[str, Any]]:
        rows = []
        for key in sorted(cells, key=lambda k: str(k)):
            c = cells[key]
            rows.append({
                "key": key, "n": int(c["n"]),
                "annual_premium": round(c["premium"], 2),
                "expected_loss_ratio_phins_tables_pct": _r(100 * c["phins_loss"] / c["premium"] if c["premium"] else 0, 2),
                "expected_loss_ratio_true_world_pct": _r(100 * c["true_loss"] / c["premium"] if c["premium"] else 0, 2),
            })
        return rows

    # Auto-approval gates are evaluated hypothetically (as if enabled) against
    # the configured limits; the live flag is reported, never changed.
    gate_pass = []
    for life in lives:
        score = life.get("uw_score")
        passes = (
            cfg.auto_approve_min_age <= life["age"] <= cfg.auto_approve_max_age
            and life["adl"] <= cfg.auto_approve_max_adl
            and life["coverage"] <= cfg.auto_approve_max_coverage
            and score is not None and score <= cfg.auto_approve_max_risk_score
            and (not cfg.auto_approve_require_clean_history or (
                life["smoking_status"] == "never" and not life["conditions"]))
        )
        life["auto_approvable"] = bool(passes)
        gate_pass.append(bool(passes))
    auto_n = sum(gate_pass)
    auto_hazard = _mean([_annual_claim_probability(l) for l in lives if l["auto_approvable"]]) if auto_n else None
    manual_hazard = _mean([_annual_claim_probability(l) for l in lives if not l["auto_approvable"]]) if auto_n < n else None
    hazards_sorted = sorted(_annual_claim_probability(l) for l in lives)
    top_decile_cut = _percentile(hazards_sorted, 0.90)
    auto_top_lives = [l for l in lives if l["auto_approvable"] and _annual_claim_probability(l) >= top_decile_cut]
    auto_top_decile = len(auto_top_lives)
    auto_top_profile = {
        "count": auto_top_decile,
        "mean_age": _r(_mean([l["age"] for l in auto_top_lives]), 1) if auto_top_lives else None,
        "mean_adl": _r(_mean([l["adl"] for l in auto_top_lives]), 2) if auto_top_lives else None,
        "mean_bmi": _r(_mean([l["bmi"] for l in auto_top_lives]), 1) if auto_top_lives else None,
        "mean_prior_claims": _r(_mean([l["claims_count"] for l in auto_top_lives]), 2) if auto_top_lives else None,
        "top_decile_hazard_cut": _r(top_decile_cut, 6),
    }

    # Decline-threshold sensitivity (deterministic expected values, priced by the kernel).
    sensitivity = []
    for threshold in sorted({int(cfg.decline_threshold) - 1, int(cfg.decline_threshold), int(cfg.decline_threshold) + 1}):
        prem = loss = 0.0
        decl = 0
        for life in lives:
            rule = _apply_uw_rules(life, cfg, threshold)
            if not rule["eligible"]:
                decl += 1
                continue
            if threshold == int(cfg.decline_threshold) and "true_expected_loss" in life:
                prem += life["premium"]
                loss += life["true_expected_loss"]
                continue
            scaled = _scaled_life(life, rule["coverage"])
            comp = _price_life(scaled, ctx, rule["loading"], rule["exclude_disability"])
            prem += float(comp.annual_premium)
            loss += _expected_annual_loss(scaled, truth=True, exclude_disability=rule["exclude_disability"])
        sensitivity.append({
            "decline_threshold_adl": threshold,
            "declined_share": _r(decl / n),
            "annual_premium": round(prem, 2),
            "expected_loss_ratio_true_world_pct": _r(100 * loss / prem if prem else 0, 2),
        })

    return {
        "lives": n, "priced": priced,
        "declined_share": _r(declined / n),
        "coverage_capped_share": _r(capped / n),
        "disability_excluded_share": _r(excluded / n),
        "portfolio_annual_premium": round(total_premium, 2),
        "expected_loss_ratio_phins_tables_pct": _r(100 * total_phins_loss / total_premium if total_premium else 0, 2),
        "expected_loss_ratio_true_world_pct": _r(100 * total_true_loss / total_premium if total_premium else 0, 2),
        "loss_ratio_by_adl": _lr_rows(by_adl),
        "loss_ratio_by_smoking_status": _lr_rows(by_smoking),
        "demographic_factors_neutral": all(
            float(getattr(cfg, name, 1.0)) == 1.0 for name in (
                "smoker_mortality_factor", "smoker_disability_factor",
                "former_smoker_mortality_factor", "former_smoker_disability_factor")),
        "auto_approval": {
            "enabled_live": bool(cfg.auto_approve_enabled),
            "evaluated_as_if_enabled": True,
            "gate_pass_share": _r(auto_n / n),
            "mean_annual_hazard_auto_approvable": _r(auto_hazard, 6),
            "mean_annual_hazard_manual_queue": _r(manual_hazard, 6),
            "auto_approvable_in_top_hazard_decile": auto_top_decile,
            "auto_approvable_top_decile_profile": auto_top_profile,
            "gates": {
                "max_adl": cfg.auto_approve_max_adl, "age": [cfg.auto_approve_min_age, cfg.auto_approve_max_age],
                "max_risk_score": cfg.auto_approve_max_risk_score,
                "max_coverage": cfg.auto_approve_max_coverage,
                "require_clean_history": cfg.auto_approve_require_clean_history,
            },
        },
        "decline_threshold_sensitivity": sensitivity,
        "reinsurance_band_true_world": act.classify_reinsurance_risk_band(
            100 * total_true_loss / total_premium if total_premium else 0),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Module 3 — actuarial metrics (stochastic claims, reserves, IBNR, lapse)
# ─────────────────────────────────────────────────────────────────────────────

def _build_cells(lives: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cells: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for life in lives:
        if not life.get("uw_rule", {}).get("eligible", True) or life.get("premium", 0.0) <= 0:
            continue
        key = (life["age"] // 5, life["adl"], life["smoking_status"], bool(life.get("exclude_disability")))
        cell = cells.setdefault(key, {"n": 0, "q": 0.0, "i": 0.0, "premium": 0.0, "hazard": 0.0,
                                      "life_sums": [], "dis_benefits": []})
        cell["n"] += 1
        cell["q"] += life["q_true"]
        cell["i"] += 0.0 if life.get("exclude_disability") else life["i_true"]
        cell["premium"] += life["premium"]
        cell["hazard"] += _annual_claim_probability(life)
        cell["life_sums"].append(life["life_sum"])
        cell["dis_benefits"].append(life["benefit_pct"] * life["disability_sum"])
    out = []
    for cell in cells.values():
        n = cell["n"]
        out.append({
            "n": n, "q": cell["q"] / n, "i": cell["i"] / n,
            "premium_per_life": cell["premium"] / n, "hazard": cell["hazard"] / n,
            "life_sums": cell["life_sums"], "dis_benefits": cell["dis_benefits"],
            "mean_life_sum": _mean(cell["life_sums"]), "mean_dis_benefit": _mean(cell["dis_benefits"]),
        })
    return out


def _hazard_tercile_cuts(cells: List[Dict[str, Any]]) -> Tuple[float, float]:
    """Exposure-weighted hazard terciles used to label healthy / impaired cells."""
    total = sum(c["n"] for c in cells)
    if total <= 0:
        return (0.0, 0.0)
    lo_cut = hi_cut = None
    running = 0
    for c in sorted(cells, key=lambda c: c["hazard"]):
        running += c["n"]
        if lo_cut is None and running >= total / 3:
            lo_cut = c["hazard"]
        if hi_cut is None and running >= 2 * total / 3:
            hi_cut = c["hazard"]
    return (lo_cut or 0.0, hi_cut or 0.0)


def _lapse_multiplier(cell: Dict[str, Any], cuts: Tuple[float, float], world: WorldAssumptions,
                      antiselection: bool) -> float:
    if not antiselection:
        return 1.0
    if cell["hazard"] <= cuts[0]:
        return world.antiselection_low_hazard_lapse_mult
    if cell["hazard"] >= cuts[1]:
        return world.antiselection_high_hazard_lapse_mult
    return 1.0


def _expected_cumulative_lr(cells: List[Dict[str, Any]], ctx: Dict[str, Any],
                            params: EvaluationParams, antiselection: bool) -> float:
    """Noise-free expected cumulative loss ratio over the horizon."""
    store = ctx["store"]
    cuts = _hazard_tercile_cuts(cells)
    exposure = [float(c["n"]) for c in cells]
    prem_total = claims_total = 0.0
    for year in range(1, params.horizon_years + 1):
        lapse = store.get_lapse_rate(year)
        for ci, cell in enumerate(cells):
            n = exposure[ci]
            prem_total += n * cell["premium_per_life"]
            claims_total += n * (cell["q"] * cell["mean_life_sum"]
                                 + (1 - cell["q"]) * cell["i"] * cell["mean_dis_benefit"])
            survivors = n * (1 - cell["q"] - (1 - cell["q"]) * cell["i"])
            mult = _lapse_multiplier(cell, cuts, params.world, antiselection)
            exposure[ci] = survivors * (1 - min(0.95, lapse * mult))
    return claims_total / prem_total if prem_total > 0 else 0.0


def _simulate_portfolio_paths(rng: random.Random, cells: List[Dict[str, Any]], ctx: Dict[str, Any],
                              params: EvaluationParams, antiselection: bool) -> Dict[str, Any]:
    store = ctx["store"]
    world = params.world
    years = params.horizon_years
    cuts = _hazard_tercile_cuts(cells)
    lag_mu = math.log(world.reporting_lag_mean_days) - 0.5 * world.reporting_lag_sigma ** 2

    year1_lr, cum_lr, ibnr_share_claims, ibnr_share_premium = [], [], [], []
    year1_claims, year_lrs = [], [[] for _ in range(years)]
    for _ in range(params.trials):
        exposure = [c["n"] for c in cells]
        cum_prem = cum_claims = 0.0
        for year in range(1, years + 1):
            prem = claims = unreported = 0.0
            lapse_rate = store.get_lapse_rate(year)
            for ci, cell in enumerate(cells):
                n = exposure[ci]
                if n <= 0:
                    continue
                prem += n * cell["premium_per_life"]
                deaths = _binomial(rng, n, cell["q"])
                disabilities = _binomial(rng, n - deaths, cell["i"])
                for _d in range(deaths):
                    sev = rng.choice(cell["life_sums"])
                    claims += sev
                    if year == 1 and rng.random() * 365 + rng.lognormvariate(lag_mu, world.reporting_lag_sigma) > 365:
                        unreported += sev
                for _d in range(disabilities):
                    sev = rng.choice(cell["dis_benefits"])
                    claims += sev
                    if year == 1 and rng.random() * 365 + rng.lognormvariate(lag_mu, world.reporting_lag_sigma) > 365:
                        unreported += sev
                survivors = n - deaths - disabilities
                mult = _lapse_multiplier(cell, cuts, world, antiselection)
                lapses = _binomial(rng, survivors, min(0.95, lapse_rate * mult))
                exposure[ci] = max(0, survivors - lapses)
            lr = claims / prem if prem > 0 else 0.0
            year_lrs[year - 1].append(lr)
            if year == 1:
                year1_lr.append(lr)
                year1_claims.append(claims)
                ibnr_share_claims.append(unreported / claims if claims > 0 else 0.0)
                ibnr_share_premium.append(unreported / prem if prem > 0 else 0.0)
            cum_prem += prem
            cum_claims += claims
        cum_lr.append(cum_claims / cum_prem if cum_prem > 0 else 0.0)
    return {
        "year1_lr": year1_lr, "cum_lr": cum_lr, "year1_claims": year1_claims,
        "ibnr_share_claims": ibnr_share_claims, "ibnr_share_premium": ibnr_share_premium,
        "year_lr_means": [_mean(v) for v in year_lrs],
    }


def evaluate_actuarial_metrics(rng: random.Random, lives: List[Dict[str, Any]],
                               params: EvaluationParams, ctx: Dict[str, Any]) -> Dict[str, Any]:
    act = ctx["act"]
    reserve_cfg = ctx["reserve_cfg"]
    cells = _build_cells(lives)
    eligible = [l for l in lives if l.get("premium", 0.0) > 0]
    premium = sum(l["premium"] for l in eligible)
    expected_true = sum(l["true_expected_loss"] for l in eligible)
    expected_phins = sum(l["phins_expected_loss"] for l in eligible)
    # PHINS's own simulator definition: annual expected claims = Σ PV claims / avg term.
    avg_term = _mean([l["term"] for l in eligible]) if eligible else 17.5
    pv_total = sum(l.get("pv_total_risk_claims", 0.0) for l in eligible)
    phins_sim_expected_claims = pv_total / avg_term if avg_term else 0.0
    reserve_requirement = phins_sim_expected_claims * 1.5

    base = _simulate_portfolio_paths(rng, cells, ctx, params, antiselection=False)
    stress = _simulate_portfolio_paths(rng, cells, ctx, params, antiselection=True)
    expected_base_lr = _expected_cumulative_lr(cells, ctx, params, antiselection=False)
    expected_stress_lr = _expected_cumulative_lr(cells, ctx, params, antiselection=True)

    y1 = base["year1_lr"]
    y1_pct = [100 * x for x in y1]
    claims_y1 = base["year1_claims"]
    ibnr_claims = base["ibnr_share_claims"]
    ibnr_prem = base["ibnr_share_premium"]
    ibnr_needed_pct_of_premium_p95 = 100 * _percentile(sorted(ibnr_prem), 0.95)
    reserves_reporting_ibnr_pct = 100 * 0.65 * 0.15  # premium × loss ratio × factor

    band_counts: Dict[str, int] = {}
    for x in y1_pct:
        band = act.classify_reinsurance_risk_band(x)
        band_counts[band] = band_counts.get(band, 0) + 1

    return {
        "eligible_lives": len(eligible), "cells": len(cells), "trials": params.trials,
        "horizon_years": params.horizon_years,
        "portfolio_annual_premium": round(premium, 2),
        "expected_annual_claims_phins_tables": round(expected_phins, 2),
        "expected_annual_claims_true_world": round(expected_true, 2),
        "phins_simulator_expected_claims_pv_over_term": round(phins_sim_expected_claims, 2),
        "expected_loss_ratio_phins_tables_pct": _r(100 * expected_phins / premium if premium else 0, 2),
        "expected_loss_ratio_true_world_pct": _r(100 * expected_true / premium if premium else 0, 2),
        "phins_simulator_loss_ratio_pct": _r(100 * phins_sim_expected_claims / premium if premium else 0, 2),
        "year1_loss_ratio_pct": _distribution(y1_pct),
        "cumulative_loss_ratio_pct": _distribution([100 * x for x in base["cum_lr"]]),
        "loss_ratio_by_year_mean_pct": [_r(100 * x, 2) for x in base["year_lr_means"]],
        "probability_year1_lr_exceeds_100pct": _r(sum(1 for x in y1 if x > 1.0) / len(y1)),
        "probability_year1_lr_exceeds_65pct_assumption": _r(sum(1 for x in y1 if x > 0.65) / len(y1)),
        "reserve_rule_150pct": {
            "reserve_requirement": round(reserve_requirement, 2),
            "probability_year1_claims_within_reserve": _r(sum(1 for c in claims_y1 if c <= reserve_requirement) / len(claims_y1)),
            "shortfall_p99": round(max(0.0, _percentile(sorted(claims_y1), 0.99) - reserve_requirement), 2),
            "multiple_needed_for_99pct_coverage": _r(_percentile(sorted(claims_y1), 0.99) / phins_sim_expected_claims if phins_sim_expected_claims else None, 3),
        },
        "ibnr": {
            "unreported_share_of_year1_claims": _distribution(ibnr_claims),
            "reserve_config_ibnr_pct_of_claims": reserve_cfg.ibnr_pct * 100,
            "probability_reserve_config_ibnr_sufficient": _r(sum(1 for s in ibnr_claims if s <= reserve_cfg.ibnr_pct) / len(ibnr_claims)),
            "unreported_pct_of_premium_p95": _r(ibnr_needed_pct_of_premium_p95, 3),
            "reserves_reporting_ibnr_pct_of_premium": _r(reserves_reporting_ibnr_pct, 3),
            "probability_reserves_reporting_ibnr_sufficient": _r(sum(1 for s in ibnr_prem if 100 * s <= reserves_reporting_ibnr_pct) / len(ibnr_prem)),
        },
        "reinsurance_band_distribution_year1": {k: _r(v / len(y1_pct)) for k, v in sorted(band_counts.items())},
        "antiselection_stress": {
            "cumulative_loss_ratio_pct": _distribution([100 * x for x in stress["cum_lr"]]),
            "loss_ratio_by_year_mean_pct": [_r(100 * x, 2) for x in stress["year_lr_means"]],
            "expected_cumulative_lr_base_pct": _r(100 * expected_base_lr, 3),
            "expected_cumulative_lr_stress_pct": _r(100 * expected_stress_lr, 3),
            "cumulative_lr_drift_pct_points": _r(100 * (expected_stress_lr - expected_base_lr), 3),
            "mc_mean_drift_pct_points": _r(100 * (_mean(stress["cum_lr"]) - _mean(base["cum_lr"])), 3),
            "lapse_multipliers": {"low_hazard_tercile": params.world.antiselection_low_hazard_lapse_mult,
                                  "high_hazard_tercile": params.world.antiselection_high_hazard_lapse_mult},
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Module 4 — claims triage
# ─────────────────────────────────────────────────────────────────────────────

def _recommend_with_thresholds(authenticity: float, critical: bool, investigation: bool,
                               has_hidden: bool, causal_hidden: bool, within_contest: bool,
                               approve_full: float, approve_partial: float, deny: float) -> str:
    """Mirror of ``ClaimsBotService._make_recommendation`` with movable thresholds."""
    if authenticity >= approve_full and not critical and not causal_hidden:
        return "approve_full"
    if authenticity >= approve_partial and not critical:
        return "refer_medical_review" if has_hidden else "approve_partial"
    if causal_hidden and within_contest:
        return "deny_hidden_condition"
    if critical:
        return "refer_investigation"
    if investigation:
        return "refer_investigation"
    if authenticity < deny:
        return "deny_fraud_suspected"
    return "pending_more_info"


def evaluate_claims_triage(rng: random.Random, params: EvaluationParams,
                           ctx: Dict[str, Any]) -> Dict[str, Any]:
    from services.claims_bot_service import (
        ClaimsBotService, FraudIndicator, FraudIndicatorType, HiddenCondition,
    )

    world = params.world
    weights = ClaimsBotService.SCORE_WEIGHTS
    # _make_recommendation is stateless; bypass __init__ (which prints/logs).
    bot = ClaimsBotService.__new__(ClaimsBotService)
    n = max(1_000, params.lives)
    approve_set = {"approve_full", "approve_partial"}
    deny_set = {"deny_fraud_suspected", "deny_hidden_condition"}
    manual_set = {"refer_investigation", "refer_medical_review", "pending_more_info"}

    records = []
    mismatches = 0
    for _ in range(n):
        fraud = rng.random() < world.fraud_rate
        amount = rng.lognormvariate(math.log(20_000.0), 0.9)
        # Component evidence is deliberately overlapping: fraud is not obvious.
        if fraud:
            comps = [rng.betavariate(4.5, 3.0) for _ in range(6)]
            n_ind = _poisson(rng, 0.8)
            sev = [rng.uniform(0.3, 0.95) for _ in range(n_ind)]
            has_hidden = rng.random() < 0.30
            causal = has_hidden and rng.random() < 0.70
        else:
            comps = [rng.betavariate(7.0, 2.0) for _ in range(6)]
            n_ind = _poisson(rng, 0.25)
            sev = [rng.uniform(0.2, 0.7) for _ in range(n_ind)]
            has_hidden = rng.random() < 0.04
            causal = has_hidden and rng.random() < 0.30
        concealment = rng.uniform(0.3, 0.9) if has_hidden else 0.0
        within_contest = rng.random() < world.contestability_share
        base = sum(c * w for c, w in zip(comps, weights.values()))
        authenticity = max(0.0, min(1.0, base - sum(s * 0.1 for s in sev) - (concealment * 0.3 if has_hidden else 0.0)))

        indicators = [FraudIndicator(
            id=f"FI-{k}", indicator_type=FraudIndicatorType.AMOUNT_SUSPICIOUS, severity=s,
            evidence=[], explanation="", recommendation="", requires_investigation=s > 0.6,
        ) for k, s in enumerate(sev)]
        hidden = [HiddenCondition(
            condition_name="synthetic", icd_code="", evidence_source="synthetic",
            detection_confidence=0.8, estimated_onset_date=None, was_before_policy=True,
            causal_link_to_claim=causal, severity="moderate", deliberate_concealment_score=concealment,
        )] if has_hidden else []
        decision, _conf, _expl = bot._make_recommendation(authenticity, indicators, hidden, within_contest, {})
        decision_value = decision.value
        mirror = _recommend_with_thresholds(
            authenticity, any(s > 0.8 for s in sev), any(s > 0.6 for s in sev), has_hidden, causal,
            within_contest, 0.85, 0.70, 0.45)
        mismatches += int(mirror != decision_value)
        records.append({
            "fraud": fraud, "amount": amount, "auth": authenticity, "decision": decision_value,
            "critical": any(s > 0.8 for s in sev), "investigation": any(s > 0.6 for s in sev),
            "has_hidden": has_hidden, "causal": causal, "within_contest": within_contest,
        })

    def _summarize(decisions: Sequence[str]) -> Dict[str, Any]:
        frauds = [r for r in records if r["fraud"]]
        legits = [r for r in records if not r["fraud"]]
        fraud_paid = [(r, d) for r, d in zip(records, decisions) if r["fraud"] and d in approve_set]
        legit_denied = [(r, d) for r, d in zip(records, decisions) if not r["fraud"] and d in deny_set]
        legit_manual = sum(1 for r, d in zip(records, decisions) if not r["fraud"] and d in manual_set)
        total_fraud_amount = sum(r["amount"] for r in frauds) or 1.0
        mix: Dict[str, int] = {}
        for d in decisions:
            mix[d] = mix.get(d, 0) + 1
        denials = [(r, d) for r, d in zip(records, decisions) if d in deny_set]
        return {
            "decision_mix": {k: _r(v / len(decisions)) for k, v in sorted(mix.items())},
            "auto_approve_share": _r(sum(1 for d in decisions if d in approve_set) / len(decisions)),
            "auto_deny_share": _r(sum(1 for d in decisions if d in deny_set) / len(decisions)),
            "manual_share": _r(sum(1 for d in decisions if d in manual_set) / len(decisions)),
            "fraud_leakage_rate": _r(len(fraud_paid) / len(frauds)) if frauds else None,
            "fraud_leakage_amount_share": _r(sum(r["amount"] for r, _ in fraud_paid) / total_fraud_amount) if frauds else None,
            "legit_false_denial_rate": _r(len(legit_denied) / len(legits)) if legits else None,
            "legit_manual_friction_rate": _r(legit_manual / len(legits)) if legits else None,
            "denial_precision": _r(sum(1 for r, _ in denials if r["fraud"]) / len(denials)) if denials else None,
        }

    live = _summarize([r["decision"] for r in records])
    auth_fraud = [r["auth"] for r in records if r["fraud"]]
    auth_legit = [r["auth"] for r in records if not r["fraud"]]
    auc = auc_score([r["auth"] for r in records], [0 if r["fraud"] else 1 for r in records])

    # The partial-approval cut-off is the lever that admits fraud (anything
    # >= it and non-critical is paid); approve_full only splits full/partial.
    sweep = []
    for approve_partial in (0.65, 0.70, 0.75, 0.80):
        for deny in (0.40, 0.45, 0.50):
            approve_full = round(max(0.85, approve_partial + 0.05), 2)
            decisions = [_recommend_with_thresholds(
                r["auth"], r["critical"], r["investigation"], r["has_hidden"], r["causal"],
                r["within_contest"], approve_full, approve_partial, deny) for r in records]
            s = _summarize(decisions)
            sweep.append({"approve_full": approve_full, "approve_partial": approve_partial, "deny": deny,
                          "fraud_leakage_rate": s["fraud_leakage_rate"],
                          "fraud_leakage_amount_share": s["fraud_leakage_amount_share"],
                          "legit_false_denial_rate": s["legit_false_denial_rate"],
                          "legit_manual_friction_rate": s["legit_manual_friction_rate"],
                          "manual_share": s["manual_share"]})

    assumed = ctx["assumptions"]["automation_base_rates"]["claims"]
    return {
        "claims_simulated": n, "fraud_rate_world": world.fraud_rate,
        "mirror_agreement_with_live_recommender": _r(1 - mismatches / n),
        "authenticity_auc_legit_vs_fraud": _r(auc),
        "authenticity_mean_legit": _r(_mean(auth_legit)), "authenticity_mean_fraud": _r(_mean(auth_fraud)),
        "live_thresholds": live,
        "assumed_automation_mix": assumed,
        "auto_approve_share_vs_assumed": _r((live["auto_approve_share"] or 0) - (assumed["auto_approve"] + assumed["auto_partial"])),
        "manual_share_vs_assumed": _r((live["manual_share"] or 0) - assumed["manual_review"]),
        "threshold_sweep": sweep,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Module 5 — sales / revenue forecast assumptions
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_sales_assumptions(rng: random.Random, lives: List[Dict[str, Any]],
                               params: EvaluationParams, ctx: Dict[str, Any],
                               observed_mrr: Optional[float]) -> Dict[str, Any]:
    world = params.world
    store = ctx["store"]
    growth = ctx["assumptions"]["bi_revenue_forecast"]["monthly_growth_default"]
    months = ctx["assumptions"]["bi_revenue_forecast"]["months_ahead_default"]
    synthetic_mrr = sum(l.get("premium", 0.0) for l in lives) / 12.0
    mrr0 = observed_mrr if observed_mrr and observed_mrr > 0 else synthetic_mrr
    if mrr0 <= 0:
        mrr0 = 1.0
    monthly_churn = 1 - (1 - store.get_lapse_rate(1)) ** (1 / 12)
    deterministic = [mrr0 * (1 + growth) ** m for m in range(1, months + 1)]

    paths: List[List[float]] = []
    for _ in range(params.trials):
        mrr = mrr0
        g_prev = growth
        path = []
        for _m in range(months):
            g = growth + world.growth_autocorrelation * (g_prev - growth) + world.monthly_growth_sd * rng.gauss(0, 1)
            g_prev = g
            shock = world.shock_magnitude if rng.random() < world.shock_probability_monthly else 0.0
            mrr = max(0.0, mrr * (1 + g - monthly_churn) * (1 + shock))
            path.append(mrr)
        paths.append(path)

    def _at(m: int) -> Dict[str, Any]:
        vals = [p[m - 1] for p in paths]
        det = deterministic[m - 1]
        dist = _distribution([v / mrr0 for v in vals])
        return {
            "month": m, "deterministic_multiple": _r(det / mrr0),
            "mc_multiple": dist,
            "probability_meets_deterministic": _r(sum(1 for v in vals if v >= det) / len(vals)),
            "probability_below_start": _r(sum(1 for v in vals if v < mrr0) / len(vals)),
            "mean_shortfall_vs_deterministic_pct": _r(100 * (1 - _mean(vals) / det) if det else None, 2),
        }

    checkpoints = [_at(m) for m in (3, 6, months) if m <= months]
    return {
        "mrr_start": round(mrr0, 2), "mrr_source": "observed_policies" if observed_mrr else "synthetic_portfolio",
        "phins_forecast": {"monthly_growth": growth, "implied_annual_growth_pct": _r(100 * ((1 + growth) ** 12 - 1), 2),
                           "churn_modelled": False},
        "world": {"monthly_churn_from_lapse_year1": _r(monthly_churn, 5), "monthly_growth_sd": world.monthly_growth_sd,
                  "growth_autocorrelation": world.growth_autocorrelation,
                  "shock_probability_monthly": world.shock_probability_monthly,
                  "shock_magnitude": world.shock_magnitude},
        "checkpoints": checkpoints,
        "trials": params.trials,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Module 6 — AI usage thresholds
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_ai_thresholds(rng: random.Random, params: EvaluationParams,
                           ctx: Dict[str, Any]) -> Dict[str, Any]:
    from services.llm_providers import review_disposition

    world = params.world
    n = max(2_000, params.lives)
    accept, review, cap = ctx["ai_accept"], ctx["ai_review"], ctx["advisory_cap"]

    outputs = []
    for _ in range(n):
        correct = rng.random() < world.ai_accuracy
        conf = rng.betavariate(7.0, 2.0) if correct else rng.betavariate(4.0, 3.0)
        outputs.append((correct, conf))

    def _dispose(conf_fn) -> Dict[str, Any]:
        counts = {"accepted": 0, "flagged": 0, "needs_review": 0}
        accepted_errors = 0
        errors_total = 0
        for correct, conf in outputs:
            d = conf_fn(conf)
            counts[d] += 1
            if not correct:
                errors_total += 1
                if d == "accepted":
                    accepted_errors += 1
        acc = counts["accepted"]
        return {
            "disposition_mix": {k: _r(v / n) for k, v in counts.items()},
            "error_rate_among_accepted": _r(accepted_errors / acc) if acc else None,
            "share_of_errors_routed_to_humans": _r(1 - accepted_errors / errors_total) if errors_total else None,
            "human_review_load": _r((counts["flagged"] + counts["needs_review"]) / n),
            "expected_cost_units_per_1000": _r(1000 * (accepted_errors * world.ai_error_cost_units
                                                        + (counts["flagged"] + counts["needs_review"]) * world.ai_review_cost_units) / n, 2),
        }

    live = _dispose(review_disposition)
    capped = _dispose(lambda c: review_disposition(min(c, cap))) if cap is not None else None

    sweep = []
    best = None
    for a in (0.70, 0.75, 0.80, 0.85, 0.90, 0.95):
        rv = min(review, a - 0.05)
        s = _dispose(lambda c, a=a, rv=rv: "accepted" if c >= a else "flagged" if c >= rv else "needs_review")
        row = {"accept": a, "review": _r(rv, 3), **s}
        sweep.append(row)
        if best is None or (row["expected_cost_units_per_1000"] or 0) < (best["expected_cost_units_per_1000"] or 0):
            best = row

    # Underwriting automation thresholds (ai_threshold_config): approve if
    # model score >= 0.85, reject if <= 0.15, else manual.
    approve_t = ctx["assumptions"]["ai_underwriting_thresholds"]["approve"]
    reject_t = ctx["assumptions"]["ai_underwriting_thresholds"]["reject"]
    good_bad = []
    for _ in range(n):
        bad = rng.random() < world.uw_bad_applicant_rate
        score = rng.betavariate(2.0, 5.0) if bad else rng.betavariate(6.0, 2.0)
        good_bad.append((bad, score))
    auto_approved = [(b, s) for b, s in good_bad if s >= approve_t]
    auto_rejected = [(b, s) for b, s in good_bad if s <= reject_t]
    manual = n - len(auto_approved) - len(auto_rejected)
    bads = sum(1 for b, _ in good_bad if b)
    goods = n - bads

    return {
        "outputs_simulated": n, "world_ai_accuracy": world.ai_accuracy,
        "live_thresholds": {"accept": accept, "review": review, "advisory_confidence_cap": cap},
        "review_disposition_live": live,
        "review_disposition_with_advisory_cap": capped,
        "advisory_cap_forces_full_human_review": bool(cap is not None and cap < review),
        "threshold_sweep": sweep,
        "lowest_cost_threshold": {"accept": best["accept"], "review": best["review"]} if best else None,
        "cost_units": {"error": world.ai_error_cost_units, "review": world.ai_review_cost_units},
        "underwriting_automation": {
            "approve_threshold": approve_t, "reject_threshold": reject_t,
            "bad_applicant_rate_world": world.uw_bad_applicant_rate,
            "auto_approve_share": _r(len(auto_approved) / n),
            "auto_reject_share": _r(len(auto_rejected) / n),
            "manual_share": _r(manual / n),
            "false_approve_rate_among_bad": _r(sum(1 for b, _ in auto_approved if b) / bads) if bads else None,
            "false_reject_rate_among_good": _r(sum(1 for b, _ in auto_rejected if not b) / goods) if goods else None,
            "bad_share_among_auto_approved": _r(sum(1 for b, _ in auto_approved if b) / len(auto_approved)) if auto_approved else None,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Observed inputs (read-only aggregates)
# ─────────────────────────────────────────────────────────────────────────────

def _observed_summary(observed: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not observed:
        return {"used": False}
    policies = observed.get("policies") or {}
    claims = observed.get("claims") or {}
    active = [p for p in policies.values() if isinstance(p, dict) and str(p.get("status", "")).lower() == "active"]
    mrr = 0.0
    for p in active:
        try:
            mrr += float(p.get("monthly_premium") or 0)
        except (TypeError, ValueError):
            pass
    approved = sum(1 for c in claims.values() if isinstance(c, dict) and str(c.get("status", "")).lower() in ("approved", "paid"))
    return {
        "used": True,
        "policies_total": len(policies), "policies_active": len(active),
        "observed_mrr": round(mrr, 2),
        "claims_total": len(claims), "claims_approved_or_paid": approved,
        "claims_per_policy": _r(len(claims) / len(policies)) if policies else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────

def run_evaluation(params: Optional[EvaluationParams] = None,
                   observed: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run the requested modules and return a JSON-ready, hash-sealed report."""
    params = (params or EvaluationParams()).normalized()
    started = datetime.now(timezone.utc)
    observed_fp_before = _sha256_of(observed) if observed is not None else None

    ctx = _load_phins_context()
    rng = random.Random(params.seed)
    modules = set(params.modules)
    needs_population = bool(modules & {"risk", "underwriting", "actuarial", "sales"})
    lives = _generate_population(rng, params.lives, ctx, params.world) if needs_population else []

    results: Dict[str, Any] = {}
    # Population-dependent modules run in dependency order regardless of selection.
    if needs_population:
        risk = evaluate_risk_assessment(rng, lives, params, ctx)
        if "risk" in modules:
            results["risk"] = risk
        uw = evaluate_underwriting_rules(rng, lives, params, ctx)
        if "underwriting" in modules:
            results["underwriting"] = uw
        if "actuarial" in modules:
            results["actuarial"] = evaluate_actuarial_metrics(rng, lives, params, ctx)
        if "sales" in modules:
            obs = _observed_summary(observed)
            results["sales"] = evaluate_sales_assumptions(rng, lives, params, ctx, obs.get("observed_mrr") if obs.get("used") else None)
    if "claims" in modules:
        results["claims"] = evaluate_claims_triage(rng, params, ctx)
    if "ai" in modules:
        results["ai"] = evaluate_ai_thresholds(rng, params, ctx)

    findings = derive_findings(results, ctx)
    observed_fp_after = _sha256_of(observed) if observed is not None else None
    observed_unchanged = (observed_fp_before == observed_fp_after) if observed is not None else None
    next_moves = derive_next_moves(results, findings, ctx, observed_unchanged)
    conclusions = derive_conclusions(results, findings, next_moves, params, observed_unchanged)
    finished = datetime.now(timezone.utc)

    run_params = {
        "seed": params.seed, "lives": params.lives, "trials": params.trials,
        "horizon_years": params.horizon_years, "bootstrap_samples": params.bootstrap_samples,
        "modules": list(params.modules),
    }
    world = asdict(params.world)
    report = {
        "engine_version": ENGINE_VERSION,
        "parameters": run_params,
        "world_assumptions": world,
        "phins_assumptions": ctx["assumptions"],
        "assumption_provenance": ctx["provenance"],
        "observed_inputs": _observed_summary(observed),
        "results": results,
        "findings": findings,
        "conclusions": conclusions,
        "next_moves": next_moves,
    }
    report["integrity"] = {
        "read_only": True,
        "side_effects": [],
        "synthetic_population": True,
        "deterministic_seed": params.seed,
        "parameters_sha256": _sha256_of(run_params),
        "world_assumptions_sha256": _sha256_of(world),
        "phins_assumptions_sha256": _sha256_of(ctx["assumptions"]),
        "results_sha256": _sha256_of(results),
        "next_moves_sha256": _sha256_of(next_moves),
        "proposals_applied_by_engine": False,
        "observed_inputs_fingerprint": observed_fp_before,
        "observed_inputs_unchanged": observed_unchanged,
        "started_at": started.isoformat(),
        "duration_seconds": round((finished - started).total_seconds(), 3),
    }
    return report


# ─────────────────────────────────────────────────────────────────────────────
# Findings (rule-based interpretation of the numbers)
# ─────────────────────────────────────────────────────────────────────────────

def derive_findings(results: Dict[str, Any], ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Turn metrics into explicit, testable statements with severity."""
    findings: List[Dict[str, Any]] = []

    def add(area: str, severity: str, statement: str, metric: Any, recommendation: str) -> None:
        findings.append({"area": area, "severity": severity, "statement": statement,
                         "metric": metric, "recommendation": recommendation})

    risk = results.get("risk")
    if risk:
        auc = risk.get("auc")
        if auc is not None:
            sev = "info" if auc >= 0.70 else "warning" if auc >= 0.60 else "critical"
            add("risk", sev, f"Underwriting scorer discriminates horizon claims with AUC {auc:.3f} "
                f"(oracle on true hazard {(risk.get('oracle_auc_true_hazard') or 0):.3f}).",
                {"auc": auc, "ci95": risk.get("auc_bootstrap_ci95"), "oracle": risk["oracle_auc_true_hazard"]},
                "Track AUC per BI snapshot; investigate features when the gap to oracle widens.")
        if not risk.get("band_monotonic_in_outcomes"):
            add("risk", "warning", "Observed claim rates are not monotonic across risk bands.",
                [(row["band"], row["observed_claim_rate"]) for row in risk["calibration_by_band"]],
                "Re-order band cut-offs or widen bands with overlapping confidence intervals.")
        add("risk", "info", "The 0–1 risk score is an additive index, not a claim probability; "
            f"raw Brier {risk['brier_score_raw']:.3f} vs base-rate Brier {risk['brier_score_base_rate']:.3f}.",
            {"brier_raw": risk["brier_score_raw"], "brier_base": risk["brier_score_base_rate"]},
            "Publish band-level observed rates (isotonic map) next to the score in BI; never present the score as a probability.")
        gaps = [row for row in risk["calibration_by_band"]
                if row.get("loading_gap") is not None and row["loading_gap"] < -0.05 and row["n"] >= 30]
        if gaps:
            add("risk", "warning", "Applied premium loadings under-cover the world excess hazard in some bands.",
                [{"band": g["band"], "applied": g["applied_premium_adjustment_mean"],
                  "required": g["required_loading_vs_tables"]} for g in gaps],
                "Feed observed band loss experience into loading calibration instead of fixed 15/30/50% steps.")

    uw = results.get("underwriting")
    if uw:
        by_smoke = {row["key"]: row for row in uw.get("loss_ratio_by_smoking_status", [])}
        if uw.get("demographic_factors_neutral") and "current" in by_smoke and "never" in by_smoke:
            gap = by_smoke["current"]["expected_loss_ratio_true_world_pct"] - by_smoke["never"]["expected_loss_ratio_true_world_pct"]
            add("underwriting", "warning" if gap > 10 else "info",
                f"Smoker demographic factors are 1.0 (neutral) while the scorer penalises smoking; "
                f"smoker vs never-smoker expected loss-ratio gap is {gap:.1f} pts under world relative risks.",
                {"smoker_lr": by_smoke["current"]["expected_loss_ratio_true_world_pct"],
                 "never_lr": by_smoke["never"]["expected_loss_ratio_true_world_pct"]},
                "Set smoker_mortality_factor / smoker_disability_factor from experience so pricing and UW scoring agree.")
        aa = uw.get("auto_approval", {})
        if aa.get("auto_approvable_in_top_hazard_decile", 0) > 0:
            profile = aa.get("auto_approvable_top_decile_profile") or {}
            add("underwriting", "warning",
                f"{aa['auto_approvable_in_top_hazard_decile']} lives passing every auto-approval gate sit in the top "
                f"hazard decile (mean age {profile.get('mean_age')}, mean ADL {profile.get('mean_adl')}).",
                profile,
                "Tighten the age gate toward the table breakpoints (e.g. 50) and gate on BMI / prior claims, "
                "which are scored but not gated, before enabling auto-approval.")
        add("underwriting", "info", f"Expected loss ratio on PHINS tables {uw['expected_loss_ratio_phins_tables_pct']}% "
            f"vs {uw['expected_loss_ratio_true_world_pct']}% under world hazards; reinsurance band {uw['reinsurance_band_true_world']}.",
            uw["decline_threshold_sensitivity"],
            "Show both table-based and experience-adjusted loss ratio in the actuary dashboard.")

    actu = results.get("actuarial")
    if actu:
        p = actu["reserve_rule_150pct"]["probability_year1_claims_within_reserve"]
        add("actuarial", "info" if p >= 0.99 else "warning" if p >= 0.95 else "critical",
            f"The 150% reserve rule covers year-1 claims in {100 * p:.1f}% of trials "
            f"(99% coverage needs {actu['reserve_rule_150pct']['multiple_needed_for_99pct_coverage']}× expected).",
            actu["reserve_rule_150pct"],
            "Replace the flat 1.5× multiple with a VaR/TVaR-based requirement from this distribution.")
        ib = actu["ibnr"]
        add("actuarial", "info" if ib["probability_reserve_config_ibnr_sufficient"] >= 0.9 else "warning",
            f"IBNR 10% of claims is sufficient in {100 * ib['probability_reserve_config_ibnr_sufficient']:.1f}% of trials; "
            f"the premium-based 9.75% rule is sufficient in {100 * ib['probability_reserves_reporting_ibnr_sufficient']:.1f}%.",
            {"unreported_share": ib["unreported_share_of_year1_claims"]},
            "Reconcile the two IBNR rules (ReserveConfig vs reserves_reporting) to one lag-based estimate.")
        p100 = actu["probability_year1_lr_exceeds_100pct"]
        add("actuarial", "info" if p100 < 0.05 else "warning",
            f"P(year-1 loss ratio > 100%) = {100 * p100:.1f}%; P(> 65% assumption) = "
            f"{100 * actu['probability_year1_lr_exceeds_65pct_assumption']:.1f}%.",
            actu["year1_loss_ratio_pct"],
            "Persist the loss-ratio distribution (p50/p95/p99) as BI snapshot metrics, not only the point estimate.")
        drift = actu["antiselection_stress"]["cumulative_lr_drift_pct_points"]
        add("actuarial", "info" if abs(drift) < 3 else "warning",
            f"Anti-selective lapse shifts the {actu['horizon_years']}-year cumulative loss ratio by {drift:+.2f} pts.",
            drift, "Add a selective-lapse scenario to reserve projections; lapse is currently a flat table.")

    cl = results.get("claims")
    if cl:
        live = cl["live_thresholds"]
        add("claims", "warning" if (live.get("fraud_leakage_rate") or 0) > 0.10 else "info",
            f"Claims triage pays {100 * (live.get('fraud_leakage_rate') or 0):.1f}% of fraudulent claims and "
            f"denies {100 * (live.get('legit_false_denial_rate') or 0):.2f}% of legitimate ones "
            f"(AUC {(cl.get('authenticity_auc_legit_vs_fraud') or 0):.3f}).",
            live, "Log decision/override pairs and re-fit the six component weights; the 0.85/0.70/0.45 cut-offs are untested constants.")
        add("claims", "info" if abs(cl.get("manual_share_vs_assumed") or 0) < 0.10 else "warning",
            f"Simulated manual-review share differs from the AutomationMetrics assumption by {100 * (cl.get('manual_share_vs_assumed') or 0):+.1f} pts.",
            {"simulated": live["manual_share"], "assumed": cl["assumed_automation_mix"]["manual_review"]},
            "Drive automation KPIs from observed decision mix rather than fixed base rates.")
        if (cl.get("mirror_agreement_with_live_recommender") or 0) < 1.0:
            add("claims", "warning", "Threshold-sweep mirror disagrees with the live recommender on some cases.",
                cl["mirror_agreement_with_live_recommender"], "Treat sweep results as indicative only.")

    sales = results.get("sales")
    if sales:
        last = sales["checkpoints"][-1]
        add("sales", "warning" if (last["probability_meets_deterministic"] or 0) < 0.5 else "info",
            f"The compound {100 * sales['phins_forecast']['monthly_growth']:.0f}%/month forecast "
            f"(≈{sales['phins_forecast']['implied_annual_growth_pct']}%/yr) is met in "
            f"{100 * last['probability_meets_deterministic']:.1f}% of paths at month {last['month']}; "
            f"mean shortfall {last['mean_shortfall_vs_deterministic_pct']}%.",
            last, "Return p10/p50/p90 bands and model churn from the lapse table in /api/bi/revenue-forecast.")

    ai = results.get("ai")
    if ai:
        live = ai["review_disposition_live"]
        add("ai", "info" if (live.get("error_rate_among_accepted") or 0) <= 0.05 else "warning",
            f"At accept≥{ai['live_thresholds']['accept']} the error rate among auto-accepted AI outputs is "
            f"{100 * (live.get('error_rate_among_accepted') or 0):.1f}%; human load {100 * live['human_review_load']:.0f}%.",
            live, "Meter accepted-error rate in ai_usage_service and recalibrate thresholds from it.")
        if ai.get("advisory_cap_forces_full_human_review"):
            add("ai", "info", "The 0.4 advisory confidence cap routes every LLM assessment to human review by design.",
                ai["live_thresholds"], "Keep the cap until accepted-error telemetry exists; the review threshold is inert while it holds.")
        if ai.get("lowest_cost_threshold") and ai["lowest_cost_threshold"]["accept"] != ai["live_thresholds"]["accept"]:
            add("ai", "info", "Cost-weighted sweep prefers a different accept threshold than the live one.",
                {"live": ai["live_thresholds"]["accept"], "lowest_cost": ai["lowest_cost_threshold"], "costs": ai["cost_units"]},
                "Decide thresholds from an explicit cost ratio, then persist the ratio with the threshold config.")
        uwa = ai["underwriting_automation"]
        add("ai", "warning" if (uwa.get("false_approve_rate_among_bad") or 0) > 0.05 else "info",
            f"AI underwriting gates (approve≥{uwa['approve_threshold']}, reject≤{uwa['reject_threshold']}) auto-approve "
            f"{100 * (uwa.get('false_approve_rate_among_bad') or 0):.1f}% of bad applicants and leave "
            f"{100 * uwa['manual_share']:.0f}% manual.", uwa,
            "Calibrate per-segment thresholds from override data (ai_threshold_config.calibrate_thresholds) once ≥20 samples exist.")
    return findings


# ─────────────────────────────────────────────────────────────────────────────
# Next moves (deterministic admin advisories) and BI conclusions
# ─────────────────────────────────────────────────────────────────────────────

# The only write path the advisories may point at. It is the existing, audited,
# versioned underwriting/pricing config endpoint (ActuarialTablesStore.update_config
# appends to config_history so any change can be restored from the versions bar).
UW_CONFIG_API = {"method": "POST", "path": "/api/actuarial/config",
                 "read_back": {"method": "GET", "path": "/api/actuarial/config"}}
ACTUARY_UW_LINK = "/actuary-dashboard.html#section-underwriting"
ACTUARY_RESERVES_LINK = "/actuary-dashboard.html#section-reserves"

# Thresholds that separate "assumption disagrees with the simulated world"
# (inconsistency) from "PHINS disagrees with itself" (anomaly).
_LR_ASSUMPTION_EXCEEDANCE_MAX = 0.50
_RESERVE_COVERAGE_MIN = 0.99
_IBNR_SUFFICIENCY_MIN = 0.90
_SALES_ATTAINMENT_MIN = 0.50
_CLAIMS_LEAKAGE_MAX = 0.05
_SMOKER_LR_GAP_PTS = 10.0
_METHOD_DISAGREEMENT_PTS = 5.0
_MIX_DISAGREEMENT_PTS = 0.15


def _integrity_block(kind: str, adjustable: bool, audited_by: Optional[str] = None,
                     reversible: Optional[bool] = None) -> Dict[str, Any]:
    """Every advisory states how it may be acted on without touching data itself."""
    return {
        "applied_by_engine": False,
        "requires_admin_confirmation": kind == "adjust",
        "adjustable_in_phins": adjustable,
        "audited_by": audited_by,
        "reversible": reversible,
        "verify_live_values_before_apply": kind == "adjust",
        "re_evaluate_after_apply": kind == "adjust",
    }


def _adjust_move(move_id: str, area: str, priority: int, title: str, why: str,
                 evidence: Any, current: Dict[str, Any], proposed: Dict[str, Any],
                 source_ref: str, trigger: str, ui_link: str = ACTUARY_UW_LINK) -> Dict[str, Any]:
    return {
        "id": move_id, "area": area, "priority": priority, "trigger": trigger,
        "title": title, "why": why, "evidence": evidence,
        "action": {
            "kind": "adjust",
            "adjustable_in_phins": True,
            "target": {
                "type": "underwriting_config",
                "label": "Actuary dashboard → Underwriting / Pricing Parameters",
                "api": UW_CONFIG_API,
                "payload": dict(proposed),
                "current": current,
                "proposed": proposed,
            },
            "source_ref": source_ref,
            "ui_link": ui_link,
        },
        "integrity": _integrity_block(
            "adjust", True,
            audited_by="ActuarialTablesStore.update_config (audit log + append-only config_history revision)",
            reversible=True),
    }


def _redirect_move(move_id: str, area: str, priority: int, title: str, why: str,
                   evidence: Any, source_ref: str, trigger: str, ui_link: Optional[str],
                   proposed: Optional[Dict[str, Any]] = None, kind: str = "redirect",
                   adjustable_note: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": move_id, "area": area, "priority": priority, "trigger": trigger,
        "title": title, "why": why, "evidence": evidence,
        "action": {
            "kind": kind,
            "adjustable_in_phins": False,
            "adjustable_note": adjustable_note,
            "target": {"type": "source", "proposed": proposed} if proposed else {"type": "source"},
            "source_ref": source_ref,
            "ui_link": ui_link,
        },
        "integrity": _integrity_block(kind, False),
    }


def _clamp_factor(x: float, lo: float = 1.0, hi: float = 3.0) -> float:
    return round(max(lo, min(hi, x)), 2)


def derive_next_moves(results: Dict[str, Any], findings: List[Dict[str, Any]],
                      ctx: Dict[str, Any], observed_unchanged: Optional[bool]) -> List[Dict[str, Any]]:
    """Translate findings into explicit admin advisories.

    Advisories are deterministic functions of the sealed results. Where PHINS
    exposes an audited configuration path the advisory carries an ``adjust``
    action with the exact payload plus the live values it was derived from, so
    the UI can refuse to apply it if the configuration has drifted since the
    evaluation. Everything else is a ``redirect`` to the code/dashboard that
    owns the assumption. The engine never applies anything.
    """
    moves: List[Dict[str, Any]] = []
    uw_cfg = (ctx.get("assumptions") or {}).get("underwriting_config") or {}

    if observed_unchanged is False:
        moves.append(_redirect_move(
            "integrity_observed_inputs_mutated", "integrity", 0,
            "Stop: observed inputs changed during the evaluation",
            "The fingerprint of the observed policies/claims differed after the run. Treat every "
            "number in this report as untrusted until the engine is audited.",
            {"observed_inputs_unchanged": False},
            "services/monte_carlo_evaluation_service.py:run_evaluation", "anomaly", None,
            kind="investigate"))

    uw = results.get("underwriting") or {}
    by_smoke = {row["key"]: row for row in uw.get("loss_ratio_by_smoking_status", [])}
    if uw.get("demographic_factors_neutral") and "current" in by_smoke and "never" in by_smoke:
        never_lr = by_smoke["never"]["expected_loss_ratio_true_world_pct"] or 0.0
        smoker_lr = by_smoke["current"]["expected_loss_ratio_true_world_pct"] or 0.0
        gap = smoker_lr - never_lr
        if gap > _SMOKER_LR_GAP_PTS and never_lr > 0:
            ratio = smoker_lr / never_lr
            proposed: Dict[str, Any] = {
                "smoker_mortality_factor": _clamp_factor(ratio),
                "smoker_disability_factor": _clamp_factor(ratio),
            }
            current = {k: uw_cfg.get(k) for k in proposed}
            if "former" in by_smoke:
                former_ratio = (by_smoke["former"]["expected_loss_ratio_true_world_pct"] or 0.0) / never_lr
                if former_ratio > 1.05:
                    proposed["former_smoker_mortality_factor"] = _clamp_factor(former_ratio)
                    proposed["former_smoker_disability_factor"] = _clamp_factor(former_ratio)
                    current["former_smoker_mortality_factor"] = uw_cfg.get("former_smoker_mortality_factor")
                    current["former_smoker_disability_factor"] = uw_cfg.get("former_smoker_disability_factor")
            moves.append(_adjust_move(
                "uw_smoker_demographic_factors", "underwriting", 1,
                "Align smoker pricing factors with the smoker/never loss-ratio gap",
                f"Pricing treats smokers as neutral (factor 1.0) while the risk scorer penalises smoking; "
                f"simulated smoker loss ratio {smoker_lr:.1f}% vs {never_lr:.1f}% for never-smokers "
                f"({gap:.1f} pts). Proposed factors equal the simulated loss-ratio ratio, capped at 3.0; "
                f"validate against experience before relying on them.",
                {"smoker_lr_pct": smoker_lr, "never_lr_pct": never_lr, "gap_pts": round(gap, 2),
                 "ratio": round(ratio, 3)},
                current, proposed,
                "services/actuarial_service.py:UnderwritingConfig.smoker_mortality_factor", "anomaly"))

    aa = uw.get("auto_approval") or {}
    if (aa.get("auto_approvable_in_top_hazard_decile") or 0) > 0:
        gates = aa.get("gates") or {}
        age_gate = gates.get("age") or [uw_cfg.get("auto_approve_min_age"), uw_cfg.get("auto_approve_max_age")]
        current_max_age = age_gate[1] if len(age_gate) > 1 else uw_cfg.get("auto_approve_max_age")
        profile = aa.get("auto_approvable_top_decile_profile") or {}
        proposed_max_age = 50
        if current_max_age is not None and int(current_max_age) > proposed_max_age:
            moves.append(_adjust_move(
                "uw_auto_approve_age_gate", "underwriting", 2 if aa.get("enabled_live") else 3,
                "Tighten the auto-approval age gate before enabling clean issuance",
                f"{aa['auto_approvable_in_top_hazard_decile']} lives that pass every auto-approval gate sit in the "
                f"top hazard decile (mean age {profile.get('mean_age')}, mean ADL {profile.get('mean_adl')}). "
                f"Auto-approval is currently {'ENABLED' if aa.get('enabled_live') else 'disabled'}; the gate "
                f"matters the moment it is switched on.",
                profile,
                {"auto_approve_max_age": current_max_age}, {"auto_approve_max_age": proposed_max_age},
                "services/actuarial_service.py:UnderwritingConfig.auto_approve_max_age", "inconsistency"))

    sens = uw.get("decline_threshold_sensitivity") or []
    live_thr = uw_cfg.get("decline_threshold")
    base = next((r for r in sens if r.get("decline_threshold_adl") == live_thr), None)
    if base is not None:
        better = [r for r in sens
                  if r["decline_threshold_adl"] < live_thr
                  and (base["expected_loss_ratio_true_world_pct"] - r["expected_loss_ratio_true_world_pct"]) >= 1.0
                  and (r.get("declined_share") or 0) <= 0.02]
        if better:
            pick = max(better, key=lambda r: r["decline_threshold_adl"])
            moves.append(_adjust_move(
                "uw_decline_threshold", "underwriting", 2,
                f"Lower the ADL decline threshold to {pick['decline_threshold_adl']}",
                f"Declining at ADL ≥ {pick['decline_threshold_adl']} lowers the expected loss ratio by "
                f"{base['expected_loss_ratio_true_world_pct'] - pick['expected_loss_ratio_true_world_pct']:.1f} pts "
                f"while declining {100 * pick['declined_share']:.2f}% of applicants.",
                sens, {"decline_threshold": live_thr}, {"decline_threshold": pick["decline_threshold_adl"]},
                "services/actuarial_service.py:UnderwritingConfig.decline_threshold", "inconsistency"))
        else:
            moves.append(_redirect_move(
                "uw_decline_threshold_hold", "underwriting", 3,
                f"Keep the ADL decline threshold at {live_thr}",
                "No neighbouring threshold improves the expected loss ratio by ≥ 1 pt at ≤ 2% declines; "
                "the sensitivity table supports the current rule.",
                sens, "services/actuarial_service.py:UnderwritingConfig.decline_threshold", "none",
                ACTUARY_UW_LINK, kind="monitor"))

    actu = results.get("actuarial") or {}
    if actu:
        reserve = actu.get("reserve_rule_150pct") or {}
        cover = reserve.get("probability_year1_claims_within_reserve")
        if cover is not None and cover < _RESERVE_COVERAGE_MIN:
            moves.append(_redirect_move(
                "act_reserve_multiple", "actuarial", 1,
                "Replace the flat 150% reserve multiple with a size-aware VaR/TVaR requirement",
                f"The 1.5× rule covers year-1 claims in only {100 * cover:.1f}% of trials at "
                f"{actu.get('eligible_lives')} lives; 99% coverage needs "
                f"{reserve.get('multiple_needed_for_99pct_coverage')}× expected claims. The multiple is a "
                f"hard-coded constant, so this requires a code change rather than a dashboard setting.",
                reserve, "services/actuarial_service.py:PortfolioSimulator (reserve_requirement = expected × 1.5)",
                "inconsistency", ACTUARY_RESERVES_LINK,
                proposed={"reserve_multiple": reserve.get("multiple_needed_for_99pct_coverage")},
                adjustable_note="Constant in code; not exposed via /api/actuarial/config."))
        ib = actu.get("ibnr") or {}
        suff = ib.get("probability_reserve_config_ibnr_sufficient")
        if suff is not None and suff < _IBNR_SUFFICIENCY_MIN:
            unreported = ib.get("unreported_share_of_year1_claims") or {}
            p95 = unreported.get("p95")
            proposed_ibnr = round(2 * (100.0 * p95)) / 2 if p95 is not None else None
            moves.append(_redirect_move(
                "act_ibnr_pct", "actuarial", 1,
                "Raise the IBNR provision used in reserve projections",
                f"IBNR at {ib.get('reserve_config_ibnr_pct_of_claims')}% of claims is sufficient in "
                f"{100 * suff:.1f}% of trials; the reporting-lag simulation leaves a median "
                f"{100 * (unreported.get('p50') or 0):.1f}% (p95 {100 * (p95 or 0):.1f}%) of year-1 claims "
                f"unreported. Enter the proposed percentage in the Reserves projection form; it is a per-projection "
                f"input, not a persisted setting.",
                ib, "services/actuarial_service.py:ReserveConfig.ibnr_pct", "inconsistency",
                ACTUARY_RESERVES_LINK,
                proposed={"ibnr_pct": proposed_ibnr, "basis": "p95 of unreported share"},
                adjustable_note="Per-projection input on the Reserves form (POST /api/actuarial/reserves/project)."))
        p65 = actu.get("probability_year1_lr_exceeds_65pct_assumption")
        if p65 is not None and p65 > _LR_ASSUMPTION_EXCEEDANCE_MAX:
            y1 = actu.get("year1_loss_ratio_pct") or {}
            moves.append(_redirect_move(
                "act_lr_assumption", "actuarial", 2,
                "Re-base the 65% loss-ratio assumption on the simulated distribution",
                f"P(year-1 loss ratio > 65%) = {100 * p65:.0f}%. Simulated p50 {y1.get('p50')}%, p95 {y1.get('p95')}%. "
                f"Publish the distribution rather than the point assumption.",
                y1, "services/reserves_reporting_service.py (loss_ratio_assumption 0.65)", "inconsistency",
                ACTUARY_RESERVES_LINK, proposed={"loss_ratio_assumption_pct": y1.get("p50")},
                adjustable_note="Constant in code; expose as a reporting parameter."))
        tables_lr = actu.get("expected_loss_ratio_phins_tables_pct")
        sim_lr = actu.get("phins_simulator_loss_ratio_pct")
        if tables_lr is not None and sim_lr is not None and abs(tables_lr - sim_lr) > _METHOD_DISAGREEMENT_PTS:
            moves.append(_redirect_move(
                "act_method_disagreement", "actuarial", 1,
                "Reconcile the two PHINS definitions of annual expected claims",
                f"Year-1 table-based expected loss ratio is {tables_lr}% while PortfolioSimulator's "
                f"'annual expected claims' (PV of claims over term ÷ average term, which bakes in ageing) gives "
                f"{sim_lr}% on the same lives ({abs(tables_lr - sim_lr):.1f} pts apart). The 150% reserve rule and "
                f"the dashboard loss ratio therefore measure different things; label both bases explicitly.",
                {"tables_pct": tables_lr, "simulator_pct": sim_lr},
                "services/actuarial_service.py:PortfolioSimulator vs pricing_kernel.price_policy", "anomaly",
                ACTUARY_RESERVES_LINK, kind="investigate"))

    cl = results.get("claims") or {}
    if cl:
        live = cl.get("live_thresholds") or {}
        leak = live.get("fraud_leakage_rate") or 0.0
        sweep = cl.get("threshold_sweep") or []
        assumed_manual = ((cl.get("assumed_automation_mix") or {}).get("manual_review")) or 0.45
        if leak > _CLAIMS_LEAKAGE_MAX and sweep:
            feasible = [r for r in sweep if (r.get("manual_share") or 0) <= assumed_manual]
            pick = min(feasible or sweep,
                       key=lambda r: (r.get("fraud_leakage_rate") or 0) + (r.get("legit_false_denial_rate") or 0))
            moves.append(_redirect_move(
                "claims_partial_approval_threshold", "claims", 1,
                f"Raise the claims partial-approval cut-off to {pick.get('approve_partial')}",
                f"Live thresholds pay {100 * leak:.1f}% of fraudulent claims. In the sweep, approve_partial="
                f"{pick.get('approve_partial')} / deny={pick.get('deny')} cuts leakage to "
                f"{100 * (pick.get('fraud_leakage_rate') or 0):.1f}% with manual share "
                f"{100 * (pick.get('manual_share') or 0):.0f}%.",
                {"live": live, "pick": pick},
                "services/claims_bot_service.py:ClaimsBotService._make_recommendation", "inconsistency", None,
                proposed={"approve_partial": pick.get("approve_partial"), "deny": pick.get("deny")},
                adjustable_note="Constants in code; not exposed via API."))
        mix_gap = cl.get("manual_share_vs_assumed")
        if mix_gap is not None and abs(mix_gap) > _MIX_DISAGREEMENT_PTS:
            moves.append(_redirect_move(
                "claims_automation_base_rates", "claims", 2,
                "Drive claims automation KPIs from the observed decision mix",
                f"Simulated manual-review share is {100 * live.get('manual_share', 0):.0f}% vs the fixed "
                f"AutomationMetrics assumption of {100 * assumed_manual:.0f}%.",
                {"simulated_manual": live.get("manual_share"), "assumed_manual": assumed_manual},
                "services/actuarial_service.py:AutomationMetrics.BASE_RATES", "anomaly", None,
                kind="investigate"))
        if (cl.get("mirror_agreement_with_live_recommender") or 1.0) < 1.0:
            moves.append(_redirect_move(
                "claims_mirror_disagreement", "claims", 0,
                "Evaluation mirror disagrees with the live claims recommender",
                "The threshold sweep re-implements the recommender; disagreement means the sweep cannot be trusted.",
                cl.get("mirror_agreement_with_live_recommender"),
                "services/monte_carlo_evaluation_service.py:_recommend_with_thresholds", "anomaly", None,
                kind="investigate"))

    sales = results.get("sales") or {}
    if sales.get("checkpoints"):
        last = sales["checkpoints"][-1]
        attain = last.get("probability_meets_deterministic")
        if attain is not None and attain < _SALES_ATTAINMENT_MIN:
            p50 = (last.get("mc_multiple") or {}).get("p50")
            months = last.get("month") or 12
            monthly_p50 = round(p50 ** (1.0 / months) - 1.0, 4) if p50 and p50 > 0 else None
            moves.append(_redirect_move(
                "sales_growth_assumption", "sales", 2,
                "Forecast revenue with the simulated median growth and publish bands",
                f"The {100 * sales['phins_forecast']['monthly_growth']:.0f}%/month assumption is met in "
                f"{100 * attain:.1f}% of paths at month {months}. The simulated median path implies "
                f"{100 * (monthly_p50 or 0):.2f}%/month. Pass it as growth_rate to /api/bi/revenue-forecast and "
                f"show p10/p50/p90 instead of a single line.",
                last, "services/bi_analytics_service.py:predict_revenue_forecast", "inconsistency",
                "/admin.html#analytics",
                proposed={"growth_rate": monthly_p50, "api": "GET /api/bi/revenue-forecast?growth_rate=<value>"},
                adjustable_note="Per-request query parameter; no persisted setting."))

    ai = results.get("ai") or {}
    if ai:
        live_thr_ai = ai.get("live_thresholds") or {}
        best = ai.get("lowest_cost_threshold") or {}
        if best and live_thr_ai.get("accept") is not None and best.get("accept") != live_thr_ai.get("accept"):
            moves.append(_redirect_move(
                "ai_accept_threshold", "ai", 2,
                f"Move the AI accept threshold to {best.get('accept')}",
                f"At the configured error:review cost ratio the cost-minimising accept threshold is "
                f"{best.get('accept')} (live {live_thr_ai.get('accept')}).",
                {"live": live_thr_ai, "lowest_cost": best, "costs": ai.get("cost_units")},
                "PHINS_AI_ACCEPT_THRESHOLD / services/llm_providers.py:review_disposition", "inconsistency", None,
                proposed={"PHINS_AI_ACCEPT_THRESHOLD": best.get("accept")},
                adjustable_note="Environment variable; change at deploy time."))
        else:
            moves.append(_redirect_move(
                "ai_accept_threshold_hold", "ai", 3,
                f"Keep the AI accept threshold at {live_thr_ai.get('accept')}",
                "The live threshold is already the cost minimum for the configured error:review ratio.",
                {"live": live_thr_ai, "costs": ai.get("cost_units")},
                "services/llm_providers.py:review_disposition", "none", None, kind="monitor"))
        uwa = ai.get("underwriting_automation") or {}
        if (uwa.get("false_approve_rate_among_bad") or 0) > 0.05:
            moves.append(_redirect_move(
                "ai_uw_thresholds", "ai", 1,
                "Tighten AI underwriting auto-approval",
                f"Gates approve {100 * uwa['false_approve_rate_among_bad']:.1f}% of bad applicants automatically.",
                uwa, "services/ai_threshold_config.py:ThresholdConfig", "inconsistency", None,
                adjustable_note="Promote per-segment thresholds via ai_threshold_config (recommend-only, audited)."))

    priority_order = {0: 0, 1: 1, 2: 2, 3: 3}
    moves.sort(key=lambda m: (priority_order.get(m["priority"], 9), m["area"], m["id"]))
    return moves


_AREA_LABELS = {
    "risk": "Risk assessment", "underwriting": "Underwriting rules", "actuarial": "Actuarial metrics",
    "claims": "Claims triage", "sales": "Sales assumptions", "ai": "AI usage", "integrity": "Evaluation integrity",
}

_BI_SNAPSHOT_METRICS = {
    "risk": ["risk_scorer_auc", "risk_scorer_auc_ci95", "risk_band_observed_claim_rates"],
    "underwriting": ["expected_loss_ratio_tables_pct", "expected_loss_ratio_experience_pct",
                     "loss_ratio_by_smoking_status", "auto_approval_top_decile_leak_count"],
    "actuarial": ["year1_loss_ratio_p50_p95_p99", "reserve_coverage_probability", "ibnr_sufficiency_probability",
                  "antiselection_lr_drift_pts"],
    "claims": ["claims_fraud_leakage_rate", "claims_manual_share", "claims_legit_false_denial_rate"],
    "sales": ["mrr_forecast_p10_p50_p90", "forecast_attainment_probability"],
    "ai": ["ai_accepted_error_rate", "ai_human_review_load", "ai_uw_false_approve_rate"],
}


def derive_conclusions(results: Dict[str, Any], findings: List[Dict[str, Any]],
                       next_moves: List[Dict[str, Any]], params: EvaluationParams,
                       observed_unchanged: Optional[bool]) -> Dict[str, Any]:
    """Roll findings and advisories up into a BI-facing verdict per area and overall."""
    anomalies = [m for m in next_moves if m["trigger"] == "anomaly"]
    inconsistencies = [m for m in next_moves if m["trigger"] == "inconsistency"]
    sev_counts = {"critical": 0, "warning": 0, "info": 0}
    for f in findings:
        sev_counts[f["severity"]] = sev_counts.get(f["severity"], 0) + 1

    if observed_unchanged is False or any(m["priority"] == 0 for m in next_moves):
        overall = "anomalies_detected"
    elif anomalies:
        overall = "anomalies_detected"
    elif inconsistencies or sev_counts["critical"] or sev_counts["warning"]:
        overall = "inconsistencies_detected"
    else:
        overall = "consistent"

    areas: List[Dict[str, Any]] = []
    for area in list(results.keys()) + (["integrity"] if observed_unchanged is False else []):
        area_moves = [m for m in next_moves if m["area"] == area]
        area_findings = [f for f in findings if f["area"] == area]
        if any(m["trigger"] == "anomaly" for m in area_moves):
            status = "anomalous"
        elif any(m["trigger"] == "inconsistency" for m in area_moves) or any(f["severity"] != "info" for f in area_findings):
            status = "inconsistent"
        else:
            status = "consistent"
        top = next((f for f in area_findings if f["severity"] == "critical"), None) \
            or next((f for f in area_findings if f["severity"] == "warning"), None) \
            or (area_findings[0] if area_findings else None)
        adjustable = [m["id"] for m in area_moves if m["action"]["adjustable_in_phins"]]
        areas.append({
            "area": area,
            "label": _AREA_LABELS.get(area, area),
            "status": status,
            "headline": top["statement"] if top else "No findings raised.",
            "bi_conclusion": _bi_conclusion_for(area, status, results.get(area) or {}, area_moves),
            "next_move_ids": [m["id"] for m in area_moves],
            "adjustable_move_ids": adjustable,
            "snapshot_metrics": _BI_SNAPSHOT_METRICS.get(area, []),
        })

    n_adjust = sum(1 for m in next_moves if m["action"]["kind"] == "adjust")
    headline = {
        "consistent": "PHINS assumptions are consistent with the simulated world; keep monitoring the listed KPIs.",
        "inconsistencies_detected": f"{len(inconsistencies)} assumption(s) disagree with the simulated world; "
                                    f"{n_adjust} can be adjusted from PHINS after confirmation.",
        "anomalies_detected": f"{len(anomalies)} internal inconsistenc{'y' if len(anomalies) == 1 else 'ies'} in PHINS "
                              f"rules detected alongside {len(inconsistencies)} assumption gap(s); resolve anomalies first.",
    }[overall]

    return {
        "overall_status": overall,
        "headline": headline,
        "sample": {"lives": params.lives, "trials": params.trials, "horizon_years": params.horizon_years},
        "counts": {**sev_counts, "anomalies": len(anomalies), "inconsistencies": len(inconsistencies),
                   "next_moves": len(next_moves), "adjustable_in_phins": n_adjust},
        "areas": areas,
        "bi_usage": [
            "Persist the distribution metrics listed per area in the BI snapshot; point estimates hide tail risk.",
            "Render the risk score with band-level observed claim rates; never label it a probability.",
            "Alert when the live decision mix drifts from the mix this evaluation predicts for the live thresholds.",
            "Re-run this evaluation after any config change and compare results_sha256 to the sealed baseline.",
        ],
        "ai_usage": [
            "Advisories here are deterministic and rule-based; an LLM narrative would break the hash seal and add no evidence.",
            "Keep AI outputs advisory until accepted-error telemetry exists; thresholds should be set from measured cost.",
            "Use per-segment calibration (ai_threshold_config) only once each segment has ≥ 20 logged overrides.",
        ],
    }


def _bi_conclusion_for(area: str, status: str, res: Dict[str, Any], moves: List[Dict[str, Any]]) -> str:
    """One-sentence BI reading per area, phrased for the dashboard."""
    if area == "risk":
        auc = res.get("auc")
        return (f"Scorer ranks risk (AUC {auc:.3f}) but is not calibrated as a probability; report band rates, not the score."
                if auc is not None else "Risk module not run.")
    if area == "underwriting":
        return ("Pricing and scoring disagree on smoking; align demographic factors before trusting band loss ratios."
                if any(m["id"] == "uw_smoker_demographic_factors" for m in moves)
                else "Underwriting rules price the simulated book consistently; monitor the decline sensitivity table.")
    if area == "actuarial":
        rr = (res.get("reserve_rule_150pct") or {}).get("probability_year1_claims_within_reserve")
        ib = (res.get("ibnr") or {}).get("probability_reserve_config_ibnr_sufficient")
        return (f"Reserve rule covers year-1 in {100 * (rr or 0):.0f}% of trials and IBNR is sufficient in "
                f"{100 * (ib or 0):.0f}%; publish p50/p95/p99 loss ratios instead of the 65% point assumption.")
    if area == "claims":
        live = res.get("live_thresholds") or {}
        return (f"Triage pays {100 * (live.get('fraud_leakage_rate') or 0):.1f}% of fraud with "
                f"{100 * (live.get('manual_share') or 0):.0f}% manual share; automation KPIs should follow the observed mix.")
    if area == "sales":
        last = (res.get("checkpoints") or [{}])[-1]
        return (f"Deterministic forecast attained in {100 * (last.get('probability_meets_deterministic') or 0):.0f}% of paths; "
                f"show p10/p50/p90 bands in revenue dashboards.")
    if area == "ai":
        return ("Live accept threshold is at the cost minimum; the advisory cap keeps every LLM assessment under human review."
                if status == "consistent" else
                "Cost-weighted sweep disagrees with live AI thresholds; set thresholds from an explicit cost ratio.")
    if area == "integrity":
        return "Observed inputs changed during the run; the report is untrusted."
    return "No conclusion."


# ─────────────────────────────────────────────────────────────────────────────
# Singleton accessor (mirrors other services; the service is stateless)
# ─────────────────────────────────────────────────────────────────────────────

class MonteCarloEvaluationService:
    """Thin stateless façade so callers can follow the ``get_*_service`` pattern."""

    engine_version = ENGINE_VERSION

    def run(self, params: Optional[EvaluationParams] = None,
            observed: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return run_evaluation(params, observed)


_service: Optional[MonteCarloEvaluationService] = None


def get_monte_carlo_evaluation_service() -> MonteCarloEvaluationService:
    global _service
    if _service is None:
        _service = MonteCarloEvaluationService()
    return _service


__all__ = [
    "ENGINE_VERSION", "ALL_MODULES", "WorldAssumptions", "EvaluationParams",
    "params_from_query", "run_evaluation", "derive_findings", "derive_next_moves",
    "derive_conclusions", "UW_CONFIG_API",
    "MonteCarloEvaluationService", "get_monte_carlo_evaluation_service",
    "auc_score", "brier_score", "wilson_interval", "spearman",
]
