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

def extract_risk_inputs(app: Dict[str, Any], customer: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Extract scoring inputs from an application + customer record.

    Read-only over pipeline data: values may arrive as strings (HTML forms) or
    JSON text (database rows) and are coerced defensively. Unknown values stay
    ``None`` — never defaulted — so risk is computed only from actual data.
    """
    app = app or {}
    customer = customer or {}

    questionnaire = _coerce_json_container(
        app.get("questionnaire_responses") or app.get("questionnaire"), {}
    )

    # Age: from application, questionnaire, or calculated from DOB.
    age = _optional_int(app.get("age"))
    if not age:
        age = _optional_int(questionnaire.get("age"))
    if not age and customer.get("date_of_birth"):
        try:
            dob_str = str(customer["date_of_birth"]).replace("Z", "+00:00").split("T")[0]
            dob = datetime.fromisoformat(dob_str)
            age = (datetime.now() - dob).days // 365
        except Exception:
            age = None  # DO NOT DEFAULT - leave as unknown
    if not age:
        age = _optional_int(customer.get("age"))

    # Medical data: from application record or questionnaire - NO DEFAULTS
    disability_pct = _optional_int(app.get("disability_percentage"))
    if disability_pct is None:
        disability_pct = _optional_int(questionnaire.get("disability_percentage"))

    # BMI: from application, or calculate from height/weight in questionnaire
    bmi = _optional_float(app.get("bmi"))
    if bmi is None:
        height = app.get("height_cm") or questionnaire.get("height")
        weight = app.get("weight_kg") or questionnaire.get("weight")
        if height and weight:
            try:
                height = float(height)
                weight = float(weight)
                if height > 0 and weight > 0:
                    bmi = round(weight / ((height / 100) ** 2), 1)
            except Exception:
                pass

    # Smoking status: from application or questionnaire. Coerce truthy
    # non-string values only so falsy inputs still fall back to the
    # questionnaire rather than becoming the truthy string "False".
    smoking = app.get("smoking_status")
    if smoking and not isinstance(smoking, str):
        smoking = str(smoking)
    # Hebrew smoking phrases on the application (``מעשן`` / ``עישון``) are
    # normalised to the English status labels the scorer already understands.
    if smoking:
        try:
            from services.hebrew_assessment_lexicon import smoking_status_from_hebrew
            he_status = smoking_status_from_hebrew(str(smoking))
            if he_status:
                smoking = he_status
        except ImportError:
            pass
    if not smoking and questionnaire.get("smoke") is not None:
        smoke_raw = str(questionnaire.get("smoke", "")).strip()
        smoke_val = smoke_raw.lower()
        if smoke_val in ["yes", "current", "smoker", "true"]:
            smoking = "current"
        elif smoke_val in ["former", "ex", "quit"]:
            smoking = "former"
        elif smoke_val in ["no", "never", "non-smoker", "false"]:
            smoking = "never"
        else:
            try:
                from services.hebrew_assessment_lexicon import smoking_status_from_hebrew
                he_status = smoking_status_from_hebrew(smoke_raw)
                if he_status:
                    smoking = he_status
                elif smoke_val:
                    smoking = smoke_val
            except ImportError:
                if smoke_val:
                    smoking = smoke_val

    gender = app.get("gender") or questionnaire.get("gender") or customer.get("gender")
    occupation = (
        app.get("occupation") or questionnaire.get("occupation")
        or customer.get("occupation")
    )

    # Medical conditions: the application's medical_conditions array is the
    # authoritative source (JSON string in DB, list in-memory).
    app_conditions = _coerce_json_container(app.get("medical_conditions"), [])
    medical_conditions: List[Dict[str, Any]] = []
    has_disability_from_array = False
    has_obesity_from_array = False

    if isinstance(app_conditions, list):
        for cond in app_conditions:
            if isinstance(cond, dict):
                cond_name = cond.get("condition", "").lower()
                if ("disability" in cond_name or "mobility" in cond_name
                        or "impairment" in cond_name):
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
        "medical_conditions": medical_conditions,
        "questionnaire": questionnaire,
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


__all__ = [
    "extract_risk_inputs",
    "score_risk_inputs",
    "assess_application",
    "ENGINE_VERSION",
]
