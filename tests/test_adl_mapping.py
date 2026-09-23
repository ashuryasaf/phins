"""ADL evidence mapping: clean function is not clinical ADL 5."""

from services.adl_mapping import (
    SOURCE_DAILY_FUNCTION,
    SOURCE_HEALTH_SCORE,
    SOURCE_STATED,
    SOURCE_UNSPECIFIED,
    resolve_adl_evidence,
    resolve_from_payload,
)
from services.financial_unification_service import pin_kernel_fields_on_policy
from services.pricing_shadow_service import price_application_with_kernel


def test_daily_function_uses_published_labels():
    assert resolve_adl_evidence(daily_function="full").clinical_level == 1
    assert resolve_adl_evidence(daily_function="minor").clinical_level == 2
    assert resolve_adl_evidence(daily_function="moderate").clinical_level == 4
    significant = resolve_adl_evidence(daily_function="significant")
    assert significant.clinical_level == 8
    assert significant.source == SOURCE_DAILY_FUNCTION
    assert significant.pricing_level == significant.clinical_level


def test_legacy_full_stamp_corrects_without_rewriting_other_levels():
    corrected = resolve_adl_evidence(adl_level=5, daily_function="full")
    assert corrected.clinical_level == 1
    assert corrected.legacy_corrected is True

    kept = resolve_adl_evidence(
        adl_level=5, daily_function="full", adl_level_source="stated"
    )
    assert kept.clinical_level == 5
    assert kept.source == SOURCE_STATED
    assert kept.legacy_corrected is False

    historical = resolve_adl_evidence(adl_level=8, daily_function="significant")
    assert historical.clinical_level == 8
    assert historical.legacy_corrected is False


def test_health_score_scale_is_not_copied_onto_adl():
    clean = resolve_adl_evidence(health_score=9)
    assert clean.clinical_level == 1
    assert clean.source == SOURCE_HEALTH_SCORE

    percent = resolve_adl_evidence(health_score=95)
    assert percent.clinical_level == 1

    midpoint = resolve_adl_evidence(health_score=5)
    assert midpoint.clinical_level is None
    assert midpoint.pricing_level == 5
    assert midpoint.source == SOURCE_UNSPECIFIED

    # A stated impairment wins over a clean wellness score.
    impaired = resolve_from_payload({
        "adl_level": 7,
        "adl_level_source": "stated",
        "health_score": 10,
        "questionnaire": {"daily_function": "full"},
    })
    assert impaired.clinical_level == 7


def test_missing_evidence_does_not_invent_a_clinical_level():
    missing = resolve_from_payload({"type": "phins_unified", "age": 40})
    assert missing.clinical_level is None
    assert missing.pricing_level == 5
    assert missing.source == SOURCE_UNSPECIFIED


def test_kernel_prices_full_independence_below_baseline():
    base = {
        "type": "phins_unified",
        "coverage_amount": 500000,
        "age": 40,
        "term_years": 20,
        "gender": "female",
        "smoking_status": "nonsmoker",
        "risk_score": "low",
    }
    independent = price_application_with_kernel({
        **base,
        "questionnaire": {"daily_function": "full"},
    })
    baseline = price_application_with_kernel({**base, "adl_level": 5})
    assert independent["adl_level"] == 1
    assert independent["adl_clinical_level"] == 1
    assert independent["adl_level_source"] == SOURCE_DAILY_FUNCTION
    assert independent["adl_mortality_multiplier"] < baseline["adl_mortality_multiplier"]
    assert independent["adl_disability_multiplier"] < baseline["adl_disability_multiplier"]
    assert independent["monthly"] < baseline["monthly"]

    unlabeled = price_application_with_kernel(base)
    assert unlabeled["adl_clinical_level"] is None
    assert unlabeled["adl_level_source"] == SOURCE_UNSPECIFIED
    assert unlabeled["monthly"] == baseline["monthly"]


def test_pin_does_not_store_unspecified_baseline_as_clinical_adl():
    policy = {"id": "POL-1", "annual_premium": 100}
    pin_kernel_fields_on_policy(policy, {
        "pricing_source": "pricing_kernel",
        "adl_level": 5,
        "adl_clinical_level": None,
        "adl_level_source": SOURCE_UNSPECIFIED,
        "integrity_hash": "abc",
    })
    assert "adl_level" not in policy or policy.get("adl_level") is None
    assert policy["adl_pricing_level"] == 5
    assert policy["adl_level_source"] == SOURCE_UNSPECIFIED
    assert policy["integrity_hash"] == "abc"

    issued = {"id": "POL-2"}
    pin_kernel_fields_on_policy(issued, {
        "adl_level": 1,
        "adl_clinical_level": 1,
        "adl_level_source": SOURCE_DAILY_FUNCTION,
    })
    assert issued["adl_level"] == 1
    assert issued["adl_pricing_level"] == 1
