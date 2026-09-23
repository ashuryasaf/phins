"""Resolve an applicant's ADL level from evidence.

The published actuarial scale (``services/actuarial_service.py`` and the
actuary dashboard) is:

    1 Fully Independent
    2 Minor Assistance
    3 Mild Impairment
    4 Moderate Assistance
    5 Baseline (Medium)     mortality ×1.0, disability incidence ×1.0
    6 Significant Help      underwriting loading starts
    8 Severe Impairment     disability exclusion
    9–10 decline

Chat ``daily_function`` answers describe function, not a price band:

    full         Fully independent in all activities  → 1
    minor        Minor difficulty with 1 activity     → 2
    moderate     Need help with 1–2 activities        → 4
    significant  Need help with 3 or more activities  → 8

From August 2026 (``e1952701``) the chat writer and the underwriting scorer
mapped those answers onto 5/6/7/8 and treated a missing answer as ``full``.
``significant`` stays at 8: needing help with 3 or more activities is the
published severe band (disability exclusion), and that referral path is
unchanged. ``full``, ``minor`` and ``moderate`` move onto the independent
half of the scale their labels already describe.
A clean file was therefore stored and priced as clinical ADL 5. The scorer
adds an impairment condition only at level 6 or above, so the risk report
looked medically clean while still saying "ADL functional level 5" and the
kernel applied the medium multipliers (mortality ×1.0, disability incidence
×1.0) instead of the independent multipliers (×0.8 and ×0.3).

This module is the only map. Callers stamp ``adl_level_source`` so a later
reader can tell a real ADL 5 from a pricing baseline.

Precedence:

1. ``adl_level_source == "stated"`` keeps the explicit number.
2. An explicit number that is not the legacy ``full → 5`` stamp is kept.
   Historical referrals stored ``significant`` together with ADL 8; that
   issued level stays 8. The legacy stamp is only ``daily_function=full``
   stored as 5 with no ``stated`` source.
3. ``daily_function`` via :data:`DAILY_FUNCTION_TO_ADL`.
4. A clean health score and no functional answer. Application health scores
   follow ``services/automation/quoting.py``: 1–10, higher is healthier
   (or 0–100 on the same direction). The number is never copied onto the
   ADL scale — a health score of 5 is not ADL 5.
5. Unspecified. Pricing may use the published baseline (5) but the clinical
   level stays ``None`` and the source is ``unspecified_baseline``. Risk
   reports must not present that as a finding.

Issued premiums are not rewritten. A legacy stamp is corrected on the
assessment read path and labeled; the pinned kernel components stay.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

DAILY_FUNCTION_TO_ADL = {
    "full": 1,
    "minor": 2,
    "moderate": 4,
    # 3 or more activities is the severe band (disability exclusion). It is
    # not pulled down into the loading-only levels; only the healthy answers
    # were sitting on the wrong half of the scale.
    "significant": 8,
}

# The August 2026 writer. Used only to recognise the fully-independent
# stamp (full → 5). Other legacy bands are not rewritten: an issued ADL 8
# referral stays ADL 8.
LEGACY_FULL_DAILY_FUNCTION = "full"
LEGACY_FULL_ADL = 5

# 1–10 health scale, higher is healthier (quoting.health_multiplier).
# 8+ is clean. 7 is the auto-quote default and is not treated as independent.
CLEAN_HEALTH_MIN_10 = 8
CLEAN_HEALTH_MIN_100 = 80

PRICING_BASELINE_ADL = 5

SOURCE_STATED = "stated"
SOURCE_DAILY_FUNCTION = "daily_function"
SOURCE_HEALTH_SCORE = "health_score"
SOURCE_UNSPECIFIED = "unspecified_baseline"


@dataclass(frozen=True)
class AdlResolution:
    """Clinical finding versus the level the kernel is allowed to price."""

    clinical_level: Optional[int]
    pricing_level: int
    source: str
    legacy_corrected: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "clinical_level": self.clinical_level,
            "pricing_level": self.pricing_level,
            "source": self.source,
            "legacy_corrected": self.legacy_corrected,
        }


def clamp_adl(value: Any) -> Optional[int]:
    """Return an ADL in 1–10, or None when the value is missing or junk."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        level = int(float(value))
    except (TypeError, ValueError):
        return None
    if level < 1 or level > 10:
        return None
    return level


def _clean_health_score(value: Any) -> bool:
    """True when a wellness score is clean. Never treats the number as ADL."""
    if value is None or (isinstance(value, str) and not str(value).strip()):
        return False
    try:
        score = float(value)
    except (TypeError, ValueError):
        return False
    if 0 < score <= 10:
        return score >= CLEAN_HEALTH_MIN_10
    if 10 < score <= 100:
        return score >= CLEAN_HEALTH_MIN_100
    return False


def _first_present(*candidates: Any) -> Any:
    for raw in candidates:
        if raw is None:
            continue
        if isinstance(raw, str) and not raw.strip():
            continue
        return raw
    return None


def resolve_adl_evidence(
    *,
    adl_level: Any = None,
    adl_level_source: Any = None,
    daily_function: Any = None,
    health_score: Any = None,
) -> AdlResolution:
    """Map one applicant's evidence onto the published ADL scale."""
    daily = str(daily_function or "").strip().lower()
    explicit = clamp_adl(adl_level)
    source_hint = str(adl_level_source or "").strip().lower()

    if source_hint == SOURCE_STATED and explicit is not None:
        return AdlResolution(explicit, explicit, SOURCE_STATED, False)

    if daily in DAILY_FUNCTION_TO_ADL:
        mapped = DAILY_FUNCTION_TO_ADL[daily]
        legacy_full = (
            daily == LEGACY_FULL_DAILY_FUNCTION
            and explicit == LEGACY_FULL_ADL
            and source_hint != SOURCE_STATED
        )
        if legacy_full:
            return AdlResolution(mapped, mapped, SOURCE_DAILY_FUNCTION, True)
        if explicit is not None and explicit != mapped:
            # A different stored level (underwriter override, or a historical
            # referral that paired ``significant`` with ADL 8) is evidence,
            # not the fully-independent default.
            return AdlResolution(explicit, explicit, SOURCE_STATED, False)
        return AdlResolution(mapped, mapped, SOURCE_DAILY_FUNCTION, False)

    if explicit is not None:
        origin = source_hint or SOURCE_STATED
        return AdlResolution(explicit, explicit, origin, False)

    if _clean_health_score(health_score):
        return AdlResolution(1, 1, SOURCE_HEALTH_SCORE, False)

    return AdlResolution(None, PRICING_BASELINE_ADL, SOURCE_UNSPECIFIED, False)


def _nested(payload: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    for key in keys:
        raw = payload.get(key)
        if isinstance(raw, dict):
            return raw
    return {}


def resolve_from_payload(payload: Optional[Dict[str, Any]]) -> AdlResolution:
    """Resolve ADL for a new-application / quote payload."""
    body = payload or {}
    health = _nested(body, "health")
    questionnaire = _nested(body, "questionnaire", "questionnaire_responses")
    personal = _nested(body, "personal_info", "personal")
    return resolve_adl_evidence(
        adl_level=_first_present(
            body.get("adl_level"),
            body.get("adl"),
            health.get("adl_level"),
            questionnaire.get("adl_level"),
        ),
        adl_level_source=_first_present(
            body.get("adl_level_source"),
            questionnaire.get("adl_level_source"),
            health.get("adl_level_source"),
        ),
        daily_function=_first_present(
            body.get("daily_function"),
            questionnaire.get("daily_function"),
            health.get("daily_function"),
        ),
        health_score=_first_present(
            body.get("health_score"),
            health.get("health_score"),
            questionnaire.get("health_score"),
            personal.get("health_score"),
        ),
    )


def resolve_application_adl(
    app: Optional[Dict[str, Any]],
    questionnaire: Optional[Dict[str, Any]] = None,
) -> AdlResolution:
    """Resolve ADL for an underwriting application row (read path)."""
    record = app or {}
    form = questionnaire or {}
    health = record.get("health") if isinstance(record.get("health"), dict) else {}
    return resolve_adl_evidence(
        adl_level=_first_present(
            record.get("adl_level"),
            form.get("adl_level"),
            health.get("adl_level"),
        ),
        adl_level_source=_first_present(
            record.get("adl_level_source"),
            form.get("adl_level_source"),
        ),
        daily_function=_first_present(
            record.get("daily_function"),
            form.get("daily_function"),
        ),
        health_score=_first_present(
            record.get("health_score"),
            form.get("health_score"),
            health.get("health_score"),
        ),
    )
