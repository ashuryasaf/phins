"""
PHINS AI Threshold Configuration & Calibration (AI-2)
=====================================================
Per-segment decision thresholds for the AI automation controller, plus a
recommend-only calibration routine that learns better thresholds from the
append-only decision log (``services/ai_decision_log.py``).

Reference: ``docs/INVESTOR_AI_BI_OPTIMIZATION_REVIEW.md`` §4 (AI-2).

Why segments: a single global ``auto_approve_threshold = 0.85`` cannot be right
for a 25-year-old office worker and a 60-year-old construction worker at once.
Segmenting by ``age_band × occupation`` lets calibration tune each cohort.

Safety / data-integrity stance:
- **Zero behavior change by default.** Every segment's default thresholds equal
  the controller's historical global constants (0.85 / 0.15), so adopting this
  module changes nothing until an operator explicitly promotes calibrated values.
- **Recommend-only.** ``calibrate_thresholds`` returns *suggestions*; it never
  mutates the live config. Promotion is a separate, explicit, audited action.
- Calibration reads only the append-only decision log; it writes nothing into
  financial state.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger('phins.ai_thresholds')

# Historical global constants — the safe defaults for every segment.
DEFAULT_APPROVE_THRESHOLD = 0.85
DEFAULT_REJECT_THRESHOLD = 0.15


def age_band(age: Any) -> str:
    """Bucket an age into a coarse band used for segmentation."""
    try:
        age = int(age)
    except (TypeError, ValueError):
        return 'unknown'
    if age < 25:
        return 'under_25'
    if age < 35:
        return '25_34'
    if age < 45:
        return '35_44'
    if age < 55:
        return '45_54'
    if age < 65:
        return '55_64'
    return '65_plus'


def segment_key(application_data: Dict[str, Any]) -> str:
    """Derive a stable segment key from an application/quote payload."""
    band = age_band(application_data.get('age', 30))
    occupation = str(application_data.get('occupation', 'unknown')).lower().strip() or 'unknown'
    return f"{band}|{occupation}"


class ThresholdConfig:
    """Holds per-segment thresholds with a safe global fallback."""

    def __init__(
        self,
        default_approve: float = DEFAULT_APPROVE_THRESHOLD,
        default_reject: float = DEFAULT_REJECT_THRESHOLD,
    ):
        self.default_approve = default_approve
        self.default_reject = default_reject
        # segment_key -> {'approve': float, 'reject': float}
        self._segments: Dict[str, Dict[str, float]] = {}

    def get(self, segment: str) -> Tuple[float, float]:
        """Return (approve_threshold, reject_threshold) for a segment.

        Falls back to the global defaults when a segment has no promoted values,
        guaranteeing identical behavior to the pre-segmentation controller.
        """
        seg = self._segments.get(segment)
        if not seg:
            return self.default_approve, self.default_reject
        return (
            seg.get('approve', self.default_approve),
            seg.get('reject', self.default_reject),
        )

    def promote(self, segment: str, approve: float, reject: float) -> None:
        """Explicitly adopt calibrated thresholds for a segment (audited action)."""
        approve = max(0.0, min(1.0, float(approve)))
        reject = max(0.0, min(1.0, float(reject)))
        if reject >= approve:
            raise ValueError("reject threshold must be below approve threshold")
        self._segments[segment] = {'approve': approve, 'reject': reject}
        logger.info("Promoted thresholds for segment %s: approve=%.3f reject=%.3f",
                    segment, approve, reject)

    def as_dict(self) -> Dict[str, Any]:
        return {
            'default_approve': self.default_approve,
            'default_reject': self.default_reject,
            'segments': dict(self._segments),
        }


def calibrate_thresholds(
    decisions: List[Dict[str, Any]],
    min_samples_per_segment: int = 20,
) -> Dict[str, Any]:
    """Recommend per-segment thresholds from historical decisions + overrides.

    Approach (transparent, explainable — appropriate for regulated underwriting):
    for each segment, look at decisions a human *overrode*. If humans frequently
    overturned auto-approvals (model too lenient), nudge the approve threshold
    up; if they frequently overturned auto-rejects (model too strict), nudge the
    reject threshold down. Segments without enough samples are left on defaults.

    Returns a structured recommendation; it does NOT mutate any live config.
    """
    by_segment: Dict[str, List[Dict[str, Any]]] = {}
    for rec in decisions:
        if rec.get('decision_type') != 'underwrite':
            continue
        seg = rec.get('segment') or 'unknown'
        by_segment.setdefault(seg, []).append(rec)

    recommendations: Dict[str, Any] = {}
    for seg, recs in by_segment.items():
        sample = len(recs)
        overturned_approvals = 0
        overturned_rejections = 0
        total_overrides = 0
        for r in recs:
            override = r.get('human_override')
            if override is None:
                continue
            total_overrides += 1
            outcome = str(r.get('output', {}).get('decision', '')).lower()
            human = str(override).lower()
            if 'approve' in outcome and 'approve' not in human:
                overturned_approvals += 1
            elif 'reject' in outcome and 'reject' not in human:
                overturned_rejections += 1

        if sample < min_samples_per_segment:
            recommendations[seg] = {
                'samples': sample,
                'status': 'insufficient_data',
                'recommended_approve': DEFAULT_APPROVE_THRESHOLD,
                'recommended_reject': DEFAULT_REJECT_THRESHOLD,
            }
            continue

        approve = DEFAULT_APPROVE_THRESHOLD
        reject = DEFAULT_REJECT_THRESHOLD
        # Nudge proportionally to disagreement, capped to keep moves conservative.
        if sample:
            approve += min(0.10, (overturned_approvals / sample))
            reject -= min(0.10, (overturned_rejections / sample))
        approve = max(0.0, min(0.99, approve))
        reject = max(0.0, min(approve - 0.01, reject))

        recommendations[seg] = {
            'samples': sample,
            'overrides': total_overrides,
            'overturned_approvals': overturned_approvals,
            'overturned_rejections': overturned_rejections,
            'status': 'recommended',
            'recommended_approve': round(approve, 3),
            'recommended_reject': round(reject, 3),
        }

    return {
        'generated_segments': len(recommendations),
        'min_samples_per_segment': min_samples_per_segment,
        'recommendations': recommendations,
        'note': 'recommend-only; promote explicitly via ThresholdConfig.promote()',
    }


_threshold_config: Optional[ThresholdConfig] = None


def get_threshold_config() -> ThresholdConfig:
    global _threshold_config
    if _threshold_config is None:
        _threshold_config = ThresholdConfig()
    return _threshold_config


__all__ = [
    'ThresholdConfig',
    'get_threshold_config',
    'calibrate_thresholds',
    'segment_key',
    'age_band',
    'DEFAULT_APPROVE_THRESHOLD',
    'DEFAULT_REJECT_THRESHOLD',
]
