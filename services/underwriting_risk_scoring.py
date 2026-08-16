"""
PHINS Underwriting Risk Scoring (shared scorer)
===============================================

Single source of truth for the underwriting risk score used by

- ``GET  /api/risk-assessment/report`` (the underwriter-facing report), and
- the underwriting decision endpoints (``/api/underwriting/approve|reject``)
  and the admin pipeline gate, which snapshot the same score at decision time.

Historically this logic lived inline in the report handler only, so approval
decisions never consulted it and a second engine could drift. Extracting it
here closes that loop: one deterministic rule engine, one set of weights.

The math is a faithful extraction of the original report handler:
``overall = min(base 0.10 + age + medical + lifestyle + claims, 1.0)`` with
the same banding and recommendation thresholds. It is deliberately
deterministic and explainable (see ``docs/ai_surface_design_principles.md``).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("phins.underwriting_risk_scoring")

ENGINE_VERSION = "uw-rules-2.0.0"


# ── defensive coercion helpers (same semantics as web_portal/server.py) ──────

def _optional_int(val) -> Optional[int]:
    if val is None or (isinstance(val, str) and not val.strip()):
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def _optional_float(val) -> Optional[float]:
    if val is None or (isinstance(val, str) and not val.strip()):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _safe_float(val, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val, default: int = 0) -> int:
    if val is None:
        return default
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def _coerce_json_container(val, default):
    """dict/list pass through; JSON strings parsed; anything else → default."""
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str) and val.strip():
        try:
            parsed = json.loads(val)
        except (TypeError, ValueError):
            return default
        if isinstance(parsed, type(default)):
            return parsed
    return default


# ── input extraction ─────────────────────────────────────────────────────────

def _age_from_dob(dob_value: Any) -> Optional[int]:
    """Compute whole years from a DOB string / datetime. Unknown → None."""
    if dob_value in (None, ""):
        return None
    try:
        dob_str = str(dob_value).replace("Z", "+00:00").split("T")[0].strip()
        dob = datetime.fromisoformat(dob_str)
        return (datetime.now() - dob).days // 365
    except Exception:
        return None


def _normalize_smoking_status(raw: Any) -> Optional[str]:
    """Map chat/classic/Hebrew smoking answers onto scorer labels."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raw = str(raw)
    smoke_raw = raw.strip()
    if not smoke_raw:
        return None
    smoke_val = smoke_raw.lower()
    if smoke_val in ("yes", "current", "smoker", "true", "tobacco"):
        return "current"
    if smoke_val in ("former", "ex", "quit", "ex-smoker", "ex_smoker"):
        return "former"
    if smoke_val in ("no", "never", "non-smoker", "nonsmoker", "non_smoker", "false"):
        return "never"
    try:
        from services.hebrew_assessment_lexicon import smoking_status_from_hebrew
        he_status = smoking_status_from_hebrew(smoke_raw)
        if he_status:
            return he_status
    except ImportError:
        pass
    return smoke_val


def _adl_level_from_sources(app: Dict[str, Any], questionnaire: Dict[str, Any]) -> Optional[int]:
    """Resolve ADL severity from denormalized columns or chat answers."""
    adl = _optional_int(app.get("adl_level"))
    if adl is not None:
        return max(1, min(10, adl))
    adl = _optional_int(questionnaire.get("adl_level"))
    if adl is not None:
        return max(1, min(10, adl))
    daily = str(questionnaire.get("daily_function") or "").strip().lower()
    mapping = {"full": 5, "minor": 6, "moderate": 7, "significant": 8}
    if daily in mapping:
        return mapping[daily]
    return None


def _conditions_from_chat_questionnaire(questionnaire: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Rebuild the same condition loadings the chat underwriter used.

    Chat stores free-text ``conditions_list`` plus family/hazardous/surgery
    flags rather than a pre-scored ``medical_conditions`` array. Without this
    reconstruction the risk report sees an empty file and falls back to the
    base 10% / very_low score.
    """
    conditions: List[Dict[str, Any]] = []
    medical_flag = str(questionnaire.get("medical_conditions") or "").strip().lower()
    conditions_list = questionnaire.get("conditions_list") or ""
    if medical_flag in ("yes", "true", "y") or (
        conditions_list and str(conditions_list).strip().lower() not in
        ("", "none", "no", "n/a", "na", "-")
    ):
        try:
            from services.chat_application_service import parse_conditions_text
            conditions.extend(parse_conditions_text(conditions_list))
        except Exception:
            raw = str(conditions_list).strip()
            if raw:
                conditions.append({
                    "condition": raw[:120],
                    "severity": "moderate",
                    "risk_impact": 0.10,
                    "loading_percentage": 10,
                    "exclusion_recommended": False,
                })

    fam = questionnaire.get("family_history") or []
    if isinstance(fam, str):
        fam = [p.strip() for p in fam.split(",") if p.strip()]
    if isinstance(fam, list):
        for item in fam:
            if str(item).strip().lower() not in ("", "none", "no"):
                conditions.append({
                    "condition": f"family history: {item}",
                    "risk_impact": 0.03,
                    "loading_percentage": 0,
                    "severity": "family_history",
                    "exclusion_recommended": False,
                })

    hazardous = str(questionnaire.get("hazardous")
                    or questionnaire.get("hazardous_activities") or "").lower()
    if hazardous == "regular":
        conditions.append({
            "condition": "regular hazardous activities",
            "risk_impact": 0.08, "loading_percentage": 10,
            "severity": "lifestyle", "exclusion_recommended": False,
        })
    elif hazardous == "occasional":
        conditions.append({
            "condition": "occasional hazardous activities",
            "risk_impact": 0.04, "loading_percentage": 5,
            "severity": "lifestyle", "exclusion_recommended": False,
        })

    if str(questionnaire.get("surgery") or "").lower() == "yes":
        surgery_list = str(questionnaire.get("surgery_list") or "")[:120]
        conditions.append({
            "condition": f"recent surgery: {surgery_list}" if surgery_list
            else "recent surgery",
            "risk_impact": 0.05, "loading_percentage": 5,
            "severity": "history", "exclusion_recommended": False,
        })
    return conditions


def extract_risk_inputs(app: Dict[str, Any], customer: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Extract scoring inputs from an application + customer record.

    Read-only over pipeline data: values may arrive as strings (HTML forms) or
    JSON text (database rows) and are coerced defensively. Unknown values stay
    ``None`` — never defaulted — so risk is computed only from actual data.

    Understands both the classic apply-form shape and the chat senior-referral
    questionnaire (``dob``, ``tobacco``, ``conditions_list``, ``daily_function``).
    """
    app = app or {}
    customer = customer or {}

    questionnaire = _coerce_json_container(
        app.get("questionnaire_responses") or app.get("questionnaire"), {}
    )
    data_sources = _coerce_json_container(app.get("data_sources"), {})
    stored_assessment = _coerce_json_container(
        app.get("assessment") or data_sources.get("chat_assessment")
        or data_sources.get("assessment"),
        {},
    )

    # Age: from application, questionnaire, DOB fields, or customer record.
    age = _optional_int(app.get("age"))
    if not age:
        age = _optional_int(questionnaire.get("age"))
    if not age:
        age = _optional_int(stored_assessment.get("age"))
    if not age:
        age = _age_from_dob(
            questionnaire.get("dob")
            or questionnaire.get("date_of_birth")
            or app.get("dob")
            or app.get("date_of_birth")
            or customer.get("dob")
            or customer.get("date_of_birth")
        )
    if not age:
        age = _optional_int(customer.get("age"))

    # Medical data: from application record or questionnaire - NO DEFAULTS
    disability_pct = _optional_int(app.get("disability_percentage"))
    if disability_pct is None:
        disability_pct = _optional_int(questionnaire.get("disability_percentage"))

    # BMI: from application, stored assessment, or height/weight
    bmi = _optional_float(app.get("bmi"))
    if bmi is None:
        bmi = _optional_float(stored_assessment.get("bmi"))
    if bmi is None:
        height = (
            app.get("height_cm") or questionnaire.get("height")
            or questionnaire.get("height_cm")
        )
        weight = (
            app.get("weight_kg") or questionnaire.get("weight")
            or questionnaire.get("weight_kg")
        )
        if height and weight:
            try:
                height_f = float(height)
                weight_f = float(weight)
                if height_f > 0 and weight_f > 0:
                    bmi = round(weight_f / ((height_f / 100) ** 2), 1)
            except Exception:
                pass

    # Smoking: classic ``smoke`` + chat ``tobacco`` + denormalized column
    smoking = app.get("smoking_status")
    if smoking and not isinstance(smoking, str):
        smoking = str(smoking)
    smoking = _normalize_smoking_status(smoking) if smoking else None
    if not smoking:
        for key in ("smoke", "tobacco", "smoking", "smoking_status"):
            if questionnaire.get(key) is not None:
                smoking = _normalize_smoking_status(questionnaire.get(key))
                if smoking:
                    break

    gender = app.get("gender") or questionnaire.get("gender") or customer.get("gender")
    occupation = (
        app.get("occupation") or questionnaire.get("occupation")
        or customer.get("occupation")
    )
    adl_level = _adl_level_from_sources(app, questionnaire)

    # Medical conditions: structured array first, then chat questionnaire rebuild.
    app_conditions = _coerce_json_container(app.get("medical_conditions"), [])
    medical_conditions: List[Dict[str, Any]] = []
    has_disability_from_array = False
    has_obesity_from_array = False

    if isinstance(app_conditions, list):
        for cond in app_conditions:
            if isinstance(cond, dict):
                cond_name = str(cond.get("condition", "")).lower()
                if ("disability" in cond_name or "mobility" in cond_name
                        or "impairment" in cond_name or "adl" in cond_name):
                    has_disability_from_array = True
                if "obesity" in cond_name or "bmi" in cond_name:
                    has_obesity_from_array = True

                medical_conditions.append({
                    "condition": cond.get("condition", "Unknown Condition"),
                    "icd_code": cond.get("icd_code"),
                    "severity": cond.get("severity", "moderate"),
                    "status": cond.get("status"),
                    "treatment": cond.get("treatment"),
                    # Coerce numerics so downstream sums never TypeError
                    "risk_impact": _safe_float(cond.get("risk_impact"), 0.1),
                    "loading_percentage": _safe_int(cond.get("loading_percentage"), 10),
                    "exclusion_recommended": cond.get("exclusion_recommended", False),
                    "notes": cond.get("notes"),
                })
            elif isinstance(cond, str):
                cond_lower = cond.lower()
                if "disability" in cond_lower or "mobility" in cond_lower:
                    has_disability_from_array = True
                if "obesity" in cond_lower:
                    has_obesity_from_array = True
                medical_conditions.append({
                    "condition": cond,
                    "icd_code": None,
                    "severity": "moderate",
                    "status": None,
                    "treatment": None,
                    "risk_impact": 0.1,
                    "loading_percentage": 10,
                    "exclusion_recommended": False,
                })

    if not medical_conditions:
        medical_conditions.extend(_conditions_from_chat_questionnaire(questionnaire))

    # ADL functional impairment contributes to the medical risk view used by
    # underwriters (mirrors actuarial disability exclusion / loadings).
    if adl_level is not None and adl_level >= 6 and not has_disability_from_array:
        adl_impact = {6: 0.05, 7: 0.12, 8: 0.20, 9: 0.30, 10: 0.40}.get(adl_level, 0.08)
        if disability_pct is None:
            disability_pct = {6: 15, 7: 30, 8: 45, 9: 60, 10: 75}.get(adl_level, 20)
        medical_conditions.append({
            "condition": f"ADL functional impairment (level {adl_level})",
            "icd_code": "Z73.6",
            "severity": (
                "severe" if adl_level >= 8
                else "moderate" if adl_level >= 7 else "mild"
            ),
            "status": "active",
            "treatment": None,
            "risk_impact": adl_impact,
            "loading_percentage": int(adl_impact * 100),
            "exclusion_recommended": adl_level >= 8,
            "notes": f"daily_function={questionnaire.get('daily_function') or 'n/a'}",
        })
        has_disability_from_array = True

    # Only add disability from direct fields if not already in the array
    if disability_pct is not None and disability_pct > 0 and not has_disability_from_array:
        disability_type = app.get("disability_type", "Physical")
        disability_severity = (
            "severe" if disability_pct >= 50
            else "moderate" if disability_pct >= 25 else "mild"
        )
        medical_conditions.append({
            "condition": f"Disability ({disability_type})",
            "icd_code": "Z99.89",
            "severity": disability_severity,
            "status": app.get("disability_status", "chronic"),
            "treatment": app.get("disability_treatment", "Ongoing management"),
            "risk_impact": disability_pct / 100 * 0.6,
            "loading_percentage": min(disability_pct, 50),
            "exclusion_recommended": disability_pct >= 50,
            "notes": app.get("disability_notes"),
        })

    # Only add obesity from direct fields if not already in the array
    if bmi is not None and bmi >= 30 and not has_obesity_from_array:
        bmi_class = (
            "Class III (Severe)" if bmi >= 40
            else "Class II" if bmi >= 35 else "Class I"
        )
        obesity_severity = (
            "severe" if bmi >= 40 else "moderate" if bmi >= 35 else "mild"
        )
        medical_conditions.append({
            "condition": f"Obesity ({bmi_class})",
            "icd_code": "E66.9",
            "severity": obesity_severity,
            "status": "active",
            "treatment": app.get("obesity_treatment", "Dietary management, exercise program"),
            "risk_impact": (bmi - 25) / 100,
            "loading_percentage": min(int((bmi - 25) * 2), 40),
            "exclusion_recommended": False,
            "notes": f"BMI {bmi:.1f}" if bmi else None,
        })

    return {
        "age": age,
        "disability_percentage": disability_pct,
        "bmi": bmi,
        "smoking_status": smoking,
        "gender": gender,
        "occupation": occupation,
        "adl_level": adl_level,
        "medical_conditions": medical_conditions,
        "questionnaire": questionnaire,
        "stored_assessment": stored_assessment or None,
    }


# ── scoring ──────────────────────────────────────────────────────────────────

def score_risk_inputs(
    *,
    age: Optional[int],
    medical_conditions: List[Dict[str, Any]],
    smoking_status: Optional[str],
    claims_count: int = 0,
    bmi: Optional[float] = None,
    disability_pct: Optional[int] = None,
) -> Dict[str, Any]:
    """Deterministic additive risk score over actual pipeline data.

    Returns component scores, the overall score/category, and the engine
    recommendation with the associated conditions/monitoring text.
    """
    base_risk = 0.10  # Base risk for any applicant

    # Age risk factor - ONLY if age is known
    age_risk = 0
    if age is not None:
        if age > 65:
            age_risk = 0.30
        elif age > 55:
            age_risk = 0.20
        elif age > 45:
            age_risk = 0.12
        elif age > 35:
            age_risk = 0.05
        elif age < 25:
            age_risk = 0.03

    # Medical risk from conditions
    medical_risk = sum(c.get("risk_impact", 0) for c in (medical_conditions or []))

    # Lifestyle risk - ONLY if smoking status is known
    lifestyle_risk = 0
    if smoking_status:
        if smoking_status.lower() in ["current", "smoker", "yes"]:
            lifestyle_risk = 0.25
        elif smoking_status.lower() in ["former", "ex-smoker", "quit"]:
            lifestyle_risk = 0.10

    # Claims history risk - from actual claims data
    claims_risk = min(claims_count * 0.03, 0.15) if claims_count else 0

    # Overall risk calculation
    overall_risk = min(base_risk + age_risk + medical_risk + lifestyle_risk + claims_risk, 1.0)

    # Determine risk category
    if overall_risk <= 0.15:
        risk_category = "very_low"
    elif overall_risk <= 0.25:
        risk_category = "low"
    elif overall_risk <= 0.40:
        risk_category = "moderate"
    elif overall_risk <= 0.55:
        risk_category = "elevated"
    elif overall_risk <= 0.70:
        risk_category = "high"
    else:
        risk_category = "very_high"

    # Recommendation based on actual risk
    recommendation_type = "approve_standard"
    premium_adjustment = 0
    exclusions: List[str] = []
    monitoring: List[str] = []
    conditions_of_approval: List[str] = []
    confidence = 0.85

    total_loading = sum(c.get("loading_percentage", 0) for c in (medical_conditions or []))

    if risk_category == "very_low":
        recommendation_type = "auto_approve"
        confidence = 0.95
        monitoring = ["Standard annual review"]
    elif risk_category == "low":
        recommendation_type = "approve_standard"
        confidence = 0.90
        monitoring = ["Standard annual review"]
    elif risk_category == "moderate":
        recommendation_type = "approve_with_loading"
        premium_adjustment = (15 + total_loading) / 100
        confidence = 0.82
        monitoring = ["Annual health declaration"]
        if bmi and bmi >= 30:
            monitoring.append("Annual BMI assessment")
        if disability_pct:
            monitoring.append("Annual disability status update")
        conditions_of_approval = [
            f"Premium loading of {int(premium_adjustment * 100)}% applied",
            "Annual medical review required",
        ]
    elif risk_category == "elevated":
        recommendation_type = "approve_with_exclusions"
        premium_adjustment = (30 + total_loading) / 100
        for cond in (medical_conditions or []):
            if cond.get("exclusion_recommended"):
                exclusions.append(
                    f"Pre-existing condition exclusion: {cond.get('condition')}"
                )
        confidence = 0.78
        monitoring = ["Annual health declaration", "Bi-annual medical assessment"]
        if disability_pct:
            monitoring.append("Annual disability status update")
        monitoring.append("Claims monitoring for adverse patterns")
        conditions_of_approval = [
            f"Premium loading of {int(premium_adjustment * 100)}% applied",
            "Annual medical review required",
        ]
    elif risk_category == "high":
        recommendation_type = "refer_senior_uw"
        premium_adjustment = (50 + total_loading) / 100
        for cond in (medical_conditions or []):
            if cond.get("severity") in ["severe", "moderate"]:
                exclusions.append(
                    f"Pre-existing condition exclusion: {cond.get('condition')}"
                )
        confidence = 0.70
        monitoring = ["Quarterly health check-ins", "Annual medical review", "Claims monitoring"]
        conditions_of_approval = [
            "Senior underwriter approval required",
            f"Premium loading of {int(premium_adjustment * 100)}% if approved",
        ]
    else:
        recommendation_type = "decline"
        confidence = 0.75
        monitoring = ["Applicant may reapply after 12 months with improved health metrics"]

    return {
        "base_risk": base_risk,
        "age_risk": age_risk,
        "medical_risk": medical_risk,
        "lifestyle_risk": lifestyle_risk,
        "claims_risk": claims_risk,
        "overall_risk": overall_risk,
        "risk_category": risk_category,
        "recommendation_type": recommendation_type,
        "premium_adjustment": premium_adjustment,
        "confidence": confidence,
        "exclusions": exclusions,
        "monitoring": monitoring,
        "conditions_of_approval": conditions_of_approval,
        "total_loading": total_loading,
        "engine_version": ENGINE_VERSION,
    }


def assess_application(
    app: Dict[str, Any],
    customer: Optional[Dict[str, Any]] = None,
    claims_count: int = 0,
) -> Dict[str, Any]:
    """Convenience wrapper: extract inputs from an application then score them.

    Never raises: on unexpected data problems it returns a conservative
    "unknown" assessment (score None) so decision paths keep working.

    When the application already carries a chat/engine assessment snapshot and
    live re-extraction would collapse to the empty-file base score (10% /
    very_low), prefer the stored snapshot so underwriter reports match what
    the applicant was told.
    """
    try:
        inputs = extract_risk_inputs(app, customer)
        scores = score_risk_inputs(
            age=inputs["age"],
            medical_conditions=inputs["medical_conditions"],
            smoking_status=inputs["smoking_status"],
            claims_count=claims_count,
            bmi=inputs["bmi"],
            disability_pct=inputs["disability_percentage"],
        )
        scores = _reconcile_with_stored_assessment(app, inputs, scores)
        return {"inputs": inputs, **scores}
    except Exception as exc:
        logger.warning("Underwriting risk assessment failed: %s", exc)
        return {
            "inputs": {},
            "overall_risk": None,
            "risk_category": None,
            "recommendation_type": None,
            "engine_version": ENGINE_VERSION,
            "error": str(exc),
        }


_RISK_RANK = {
    "very_low": 0, "low": 1, "medium": 2, "moderate": 3,
    "elevated": 4, "high": 5, "very_high": 6,
}

_REC_RANK = {
    "auto_approve": 0,
    "approve_standard": 1,
    "approve_with_loading": 2,
    "approve_with_exclusions": 3,
    "refer_senior_uw": 4,
    "decline": 5,
}


def _reconcile_with_stored_assessment(
    app: Dict[str, Any],
    inputs: Dict[str, Any],
    scores: Dict[str, Any],
) -> Dict[str, Any]:
    """Keep report/decision scores aligned with the chat actuarial assessment.

    Prefer live re-score when extraction found real inputs. If the live score
    is only the empty-file base (0.10 / very_low / auto_approve) while the
    application record already labels the life as elevated/high or referred
    for senior review, adopt the stored snapshot instead of fabricating a
    clean bill of health.
    """
    stored = inputs.get("stored_assessment") or {}
    app_category = str(
        app.get("risk_assessment") or app.get("risk_score") or ""
    ).strip().lower()
    stored_category = str(stored.get("risk_category") or "").strip().lower()
    stored_overall = stored.get("overall_risk")
    stored_rec = stored.get("recommendation_type")
    app_rec = app.get("recommendation_type")

    live_is_base_only = (
        scores.get("overall_risk") is not None
        and float(scores["overall_risk"]) <= 0.15
        and not inputs.get("age")
        and not inputs.get("medical_conditions")
        and not inputs.get("smoking_status")
    )
    labeled_risky = _RISK_RANK.get(app_category, -1) >= _RISK_RANK["moderate"] or (
        _RISK_RANK.get(stored_category, -1) >= _RISK_RANK["moderate"]
    )
    referred = str(app_rec or stored_rec or "").lower() in (
        "refer_senior_uw", "decline"
    ) or bool(app.get("adl_declined")) or app.get("eligible") is False

    if stored and stored_overall is not None and (live_is_base_only or labeled_risky):
        try:
            overall = float(stored_overall)
        except (TypeError, ValueError):
            overall = scores.get("overall_risk")
        if overall is not None:
            scores = dict(scores)
            scores["overall_risk"] = overall
            if stored_category:
                scores["risk_category"] = stored_category
            if stored.get("confidence") is not None:
                scores["confidence"] = stored.get("confidence")
            if stored.get("premium_adjustment") is not None:
                scores["premium_adjustment"] = stored.get("premium_adjustment")
            if stored.get("age_risk") is not None:
                scores["age_risk"] = stored.get("age_risk")
            if stored.get("medical_risk") is not None:
                scores["medical_risk"] = stored.get("medical_risk")
            if stored.get("lifestyle_risk") is not None:
                scores["lifestyle_risk"] = stored.get("lifestyle_risk")
            scores["reconciled_from"] = "stored_chat_assessment"

    # Actuarial ADL decline / senior-referral flags always win over a softer
    # health-only recommendation so the report matches the chat decision.
    if referred:
        scores = dict(scores)
        preferred = str(stored_rec or app_rec or "refer_senior_uw")
        live_rec = str(scores.get("recommendation_type") or "")
        # Chat senior-review queue is an explicit human-contact path — keep the
        # chat/app recommendation (refer_senior_uw) rather than letting the
        # reconstructed ADL loading silently upgrade it to auto-decline.
        if str(app.get("source") or "") == "chat_adl_referral":
            scores["recommendation_type"] = preferred
        elif _REC_RANK.get(preferred, 0) >= _REC_RANK.get(live_rec, 0):
            scores["recommendation_type"] = preferred
        scores["senior_referral"] = True

    if labeled_risky and _RISK_RANK.get(str(scores.get("risk_category") or "").lower(), -1) < _RISK_RANK.get(app_category or stored_category, -1):
        scores = dict(scores)
        scores["risk_category"] = app_category or stored_category

    return scores


__all__ = [
    "extract_risk_inputs",
    "score_risk_inputs",
    "assess_application",
    "ENGINE_VERSION",
]
