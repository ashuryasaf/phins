"""
PHINS Agent Evaluation Harness (A6)
===================================
Replays logged agent decisions against the human outcomes that followed them,
reports precision / recall / F1 per segment, and proposes calibrated
thresholds. Also runs golden-set fixtures so a scorer or prompt change that
alters an agent's output is caught in CI.

Reference: ``docs/agent_operations_optimization_design.md`` §A6.

Data-integrity stance (same as ``ai_threshold_config``):

- **Read-only.** Everything here consumes the append-only decision log,
  assessment records, or fixture files; nothing writes to live configuration
  or financial state. ``propose_thresholds`` returns candidates — promotion is
  a separate, explicit, audited action (``ThresholdConfig.promote`` via the
  admin route).
- **Minimum-sample guard.** A segment below ``min_samples`` labelled decisions
  is reported as ``insufficient_data`` and receives no proposal, mirroring
  ``calibrate_claims_thresholds``.
- **Explicit vs implicit labels.** A human override is an explicit label. An
  automated approve/reject that was never overridden is an *implicit*
  confirmation; it is counted separately so a reader can see how much of the
  agreement rests on silence rather than review. ``human_review`` decisions
  without an override carry no label and are excluded.
"""

from __future__ import annotations

import glob
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger('phins.agent_eval')

APPROVE = 'approve'
REJECT = 'reject'
REVIEW = 'review'
LABELS = (APPROVE, REJECT, REVIEW)

DEFAULT_MIN_SAMPLES = 20
DEFAULT_TARGET_PRECISION = 0.95
# Candidate cut-offs swept by ``propose_thresholds``; coarse on purpose so a
# proposal is explainable and never over-fits a small log.
DEFAULT_APPROVE_GRID: Tuple[float, ...] = tuple(round(0.60 + 0.05 * i, 2) for i in range(8))  # 0.60 .. 0.95
DEFAULT_REJECT_GRID: Tuple[float, ...] = tuple(round(0.05 + 0.05 * i, 2) for i in range(8))   # 0.05 .. 0.40

Scorer = Callable[[float, Dict[str, float]], str]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalise_label(value: Any) -> Optional[str]:
    """Map a free-text human or automated decision onto ``LABELS``.

    ``None`` when the text carries no approve/reject/review meaning, so the
    caller can exclude the record rather than mis-label it.
    """
    text = str(value or '').strip().lower()
    if not text:
        return None
    if 'approve' in text or text in ('approved', 'paid', 'accept', 'accepted'):
        return APPROVE
    if 'reject' in text or 'deny' in text or 'denied' in text or 'decline' in text:
        return REJECT
    if 'review' in text or 'refer' in text or 'pending' in text or 'manual' in text:
        return REVIEW
    return None


def underwriting_scorer(score: float, thresholds: Dict[str, float]) -> str:
    """The rule spine of ``AIAutomationController.auto_underwrite``.

    ``score >= approve`` → approve, ``score <= reject`` → reject, else review.
    Fraud gating is not on the decision record and is therefore outside the
    replay, exactly as the claims sweep excludes fraud indicators.
    """
    if score >= float(thresholds['approve']):
        return APPROVE
    if score <= float(thresholds['reject']):
        return REJECT
    return REVIEW


# ---------------------------------------------------------------------------
# Samples
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LabelledSample:
    """One decision with the label a human (explicitly or implicitly) gave it."""

    score: float
    label: str
    segment: str = 'global'
    recorded: Optional[str] = None   # what the agent decided at the time
    explicit: bool = True            # False when the label is an un-overridden auto decision
    decision_id: Optional[str] = None


def samples_from_decision_log(
    decisions: Iterable[Dict[str, Any]],
    *,
    decision_type: str = 'underwrite',
    score_key: str = 'risk_score',
    include_implicit: bool = True,
) -> Tuple[List[LabelledSample], Dict[str, int]]:
    """Turn ``AIDecisionLog`` records into labelled samples.

    Returns ``(samples, skipped)`` where ``skipped`` explains every excluded
    record (``wrong_type``, ``no_score``, ``unlabelled``, ``unmapped_override``).
    """
    samples: List[LabelledSample] = []
    skipped = {'wrong_type': 0, 'no_score': 0, 'unlabelled': 0, 'unmapped_override': 0}
    for rec in decisions or []:
        if not isinstance(rec, dict) or rec.get('decision_type') != decision_type:
            skipped['wrong_type'] += 1
            continue
        output = rec.get('output') or {}
        score = output.get(score_key, rec.get('confidence'))
        try:
            score = float(score)
        except (TypeError, ValueError):
            skipped['no_score'] += 1
            continue
        recorded = normalise_label(output.get('decision'))
        segment = str(rec.get('segment') or 'global')
        override = rec.get('human_override')
        if override is not None:
            label = normalise_label(override)
            if label is None:
                skipped['unmapped_override'] += 1
                continue
            samples.append(LabelledSample(score, label, segment, recorded, True, rec.get('decision_id')))
            continue
        if include_implicit and recorded in (APPROVE, REJECT):
            samples.append(LabelledSample(score, recorded, segment, recorded, False, rec.get('decision_id')))
            continue
        skipped['unlabelled'] += 1
    return samples, skipped


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@dataclass
class ClassMetrics:
    precision: Optional[float]
    recall: Optional[float]
    f1: Optional[float]
    support: int          # samples whose label is this class
    predicted: int        # samples predicted as this class

    def to_dict(self) -> Dict[str, Any]:
        return {
            'precision': self.precision, 'recall': self.recall, 'f1': self.f1,
            'support': self.support, 'predicted': self.predicted,
        }


@dataclass
class SegmentReport:
    segment: str
    thresholds: Dict[str, float]
    samples: int
    explicit_labels: int
    implicit_labels: int
    status: str                                  # 'ok' | 'insufficient_data' | 'empty'
    confusion: Dict[str, Dict[str, int]]         # predicted -> label -> count
    per_class: Dict[str, ClassMetrics]
    agreement_rate: Optional[float]              # predicted == label over decided (non-review) predictions
    review_share: Optional[float]                # predictions that abstained to review
    override_rate: Optional[float]               # explicit overrides of the *recorded* decision / samples
    approved_but_rejected: int                   # replay approved, human rejected (leakage)
    rejected_but_approved: int                   # replay rejected, human approved (false denial)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'segment': self.segment,
            'thresholds': dict(self.thresholds),
            'samples': self.samples,
            'explicit_labels': self.explicit_labels,
            'implicit_labels': self.implicit_labels,
            'status': self.status,
            'confusion': {p: dict(row) for p, row in self.confusion.items()},
            'per_class': {k: v.to_dict() for k, v in self.per_class.items()},
            'agreement_rate': self.agreement_rate,
            'review_share': self.review_share,
            'override_rate': self.override_rate,
            'approved_but_rejected': self.approved_but_rejected,
            'rejected_but_approved': self.rejected_but_approved,
            'disagreement_cost': self.approved_but_rejected + self.rejected_but_approved,
        }


@dataclass
class EvalReport:
    agent_id: str
    thresholds: Dict[str, float]
    min_samples: int
    overall: SegmentReport
    segments: Dict[str, SegmentReport]
    skipped: Dict[str, int] = field(default_factory=dict)
    generated_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'read_only': True,
            'agent_id': self.agent_id,
            'thresholds': dict(self.thresholds),
            'min_samples': self.min_samples,
            'overall': self.overall.to_dict(),
            'segments': {k: v.to_dict() for k, v in sorted(self.segments.items())},
            'skipped': dict(self.skipped),
            'generated_at': self.generated_at,
        }


def confusion_counts(samples: Sequence[LabelledSample], scorer: Scorer,
                     thresholds: Dict[str, float]) -> Dict[str, Dict[str, int]]:
    """predicted -> label -> count for one threshold set (the primitive every
    sweep is built on; ``calibrate_claims_thresholds`` uses it too)."""
    table: Dict[str, Dict[str, int]] = {p: {l: 0 for l in LABELS} for p in LABELS}
    for s in samples:
        predicted = scorer(s.score, thresholds)
        table.setdefault(predicted, {l: 0 for l in LABELS})
        table[predicted][s.label] = table[predicted].get(s.label, 0) + 1
    return table


def _ratio(num: int, den: int) -> Optional[float]:
    return round(num / den, 4) if den else None


def _class_metrics(table: Dict[str, Dict[str, int]], cls: str) -> ClassMetrics:
    predicted = sum(table.get(cls, {}).values())
    support = sum(row.get(cls, 0) for row in table.values())
    tp = table.get(cls, {}).get(cls, 0)
    precision = _ratio(tp, predicted)
    recall = _ratio(tp, support)
    f1 = None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = round(2 * precision * recall / (precision + recall), 4)
    return ClassMetrics(precision, recall, f1, support, predicted)


def score_segment(segment: str, samples: Sequence[LabelledSample], scorer: Scorer,
                  thresholds: Dict[str, float], min_samples: int) -> SegmentReport:
    n = len(samples)
    table = confusion_counts(samples, scorer, thresholds)
    per_class = {cls: _class_metrics(table, cls) for cls in (APPROVE, REJECT)}
    decided = sum(sum(row.values()) for p, row in table.items() if p != REVIEW)
    agree = sum(table[p].get(p, 0) for p in (APPROVE, REJECT))
    reviewed = sum(table.get(REVIEW, {}).values())
    explicit = sum(1 for s in samples if s.explicit)
    overrides = sum(1 for s in samples if s.explicit and s.recorded is not None and s.recorded != s.label)
    if n == 0:
        status = 'empty'
    elif n < min_samples:
        status = 'insufficient_data'
    else:
        status = 'ok'
    return SegmentReport(
        segment=segment,
        thresholds=dict(thresholds),
        samples=n,
        explicit_labels=explicit,
        implicit_labels=n - explicit,
        status=status,
        confusion=table,
        per_class=per_class,
        agreement_rate=_ratio(agree, decided),
        review_share=_ratio(reviewed, n),
        override_rate=_ratio(overrides, n),
        approved_but_rejected=table.get(APPROVE, {}).get(REJECT, 0),
        rejected_but_approved=table.get(REJECT, {}).get(APPROVE, 0),
    )


def replay(
    samples: Sequence[LabelledSample],
    scorer: Scorer,
    thresholds: Dict[str, float],
    *,
    agent_id: str = 'ai_automation_controller',
    min_samples: int = DEFAULT_MIN_SAMPLES,
    segment_thresholds: Optional[Dict[str, Dict[str, float]]] = None,
    skipped: Optional[Dict[str, int]] = None,
) -> EvalReport:
    """Score every sample with ``scorer`` under ``thresholds`` and report per
    segment. ``segment_thresholds`` lets a segment be replayed under its own
    promoted cut-offs (as ``ThresholdConfig.get`` would resolve them)."""
    by_segment: Dict[str, List[LabelledSample]] = {}
    for s in samples:
        by_segment.setdefault(s.segment, []).append(s)
    segments = {}
    for seg, items in by_segment.items():
        seg_thresholds = dict(thresholds)
        if segment_thresholds and seg in segment_thresholds:
            seg_thresholds.update(segment_thresholds[seg])
        segments[seg] = score_segment(seg, items, scorer, seg_thresholds, min_samples)
    overall = score_segment('overall', list(samples), scorer, thresholds, min_samples)
    return EvalReport(agent_id=agent_id, thresholds=dict(thresholds), min_samples=int(min_samples),
                      overall=overall, segments=segments, skipped=dict(skipped or {}))


# ---------------------------------------------------------------------------
# Proposals (recommend-only)
# ---------------------------------------------------------------------------

def _precision_at(samples: Sequence[LabelledSample], scorer: Scorer,
                  thresholds: Dict[str, float], cls: str) -> Tuple[Optional[float], int]:
    table = confusion_counts(samples, scorer, thresholds)
    metrics = _class_metrics(table, cls)
    return metrics.precision, metrics.predicted


def propose_thresholds(
    samples: Sequence[LabelledSample],
    *,
    scorer: Scorer = underwriting_scorer,
    current: Optional[Dict[str, float]] = None,
    target_precision: float = DEFAULT_TARGET_PRECISION,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    approve_grid: Sequence[float] = DEFAULT_APPROVE_GRID,
    reject_grid: Sequence[float] = DEFAULT_REJECT_GRID,
    segments: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Candidate ``(approve, reject)`` per segment that meets ``target_precision``.

    For each segment with enough samples: the **lowest** approve cut-off on the
    grid whose approve-precision (share of replay-approvals the human also
    approved) reaches the target, and the **highest** reject cut-off whose
    reject-precision reaches it. Lower approve / higher reject means more
    automation, so each pick is the most automated setting that still meets
    the bar; a cut-off that predicts nothing has undefined precision and is
    never chosen. Raising ``target_precision`` can only move approve up and
    reject down (monotone), which keeps proposals explainable.

    Never mutates any live configuration.
    """
    target = float(target_precision)
    if not 0.0 < target <= 1.0:
        raise ValueError('target_precision must be in (0, 1]')
    current = dict(current or {'approve': 0.85, 'reject': 0.15})
    by_segment: Dict[str, List[LabelledSample]] = {}
    for s in samples:
        by_segment.setdefault(s.segment, []).append(s)
    wanted = set(segments) if segments is not None else set(by_segment)

    proposals: Dict[str, Any] = {}
    for seg in sorted(wanted):
        items = by_segment.get(seg, [])
        n = len(items)
        if n < int(min_samples):
            proposals[seg] = {'samples': n, 'status': 'insufficient_data',
                              'approve': current['approve'], 'reject': current['reject']}
            continue
        approve_pick = None
        approve_precision = None
        for cand in sorted(float(a) for a in approve_grid):
            precision, predicted = _precision_at(items, scorer, {'approve': cand, 'reject': 0.0}, APPROVE)
            if predicted and precision is not None and precision >= target:
                approve_pick, approve_precision = cand, precision
                break
        reject_pick = None
        reject_precision = None
        for cand in sorted((float(r) for r in reject_grid), reverse=True):
            if approve_pick is not None and cand >= approve_pick:
                continue
            precision, predicted = _precision_at(items, scorer, {'approve': 1.01, 'reject': cand}, REJECT)
            if predicted and precision is not None and precision >= target:
                reject_pick, reject_precision = cand, precision
                break
        status = 'recommended'
        notes = []
        if approve_pick is None:
            status = 'target_unreachable'
            notes.append('no approve cut-off on the grid reaches the target precision; keep current')
            approve_pick = current['approve']
        if reject_pick is None:
            if status == 'recommended':
                status = 'partial'
            notes.append('no reject cut-off on the grid reaches the target precision; keep current')
            reject_pick = current['reject']
        if reject_pick >= approve_pick:
            reject_pick = round(max(0.0, approve_pick - 0.05), 2)
            notes.append('reject lowered to stay below approve')
        replayed = score_segment(seg, items, scorer, {'approve': approve_pick, 'reject': reject_pick}, min_samples)
        proposals[seg] = {
            'samples': n,
            'status': status,
            'approve': approve_pick,
            'reject': reject_pick,
            'approve_precision': approve_precision,
            'reject_precision': reject_precision,
            'current': dict(current),
            'changes': approve_pick != current['approve'] or reject_pick != current['reject'],
            'replayed': {
                'agreement_rate': replayed.agreement_rate,
                'review_share': replayed.review_share,
                'disagreement_cost': replayed.approved_but_rejected + replayed.rejected_but_approved,
            },
            'notes': notes,
        }
    return {
        'read_only': True,
        'target_precision': target,
        'min_samples': int(min_samples),
        'proposals': proposals,
        'note': 'recommend-only; promote explicitly via POST /api/admin/ai-agents/thresholds/promote',
    }


# ---------------------------------------------------------------------------
# Agent-specific evaluation entry points (used by the admin route and CLI)
# ---------------------------------------------------------------------------

def evaluate_automation_controller(
    decisions: Optional[Iterable[Dict[str, Any]]] = None,
    *,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    target_precision: float = DEFAULT_TARGET_PRECISION,
    include_implicit: bool = True,
) -> Dict[str, Any]:
    """Replay the controller's ``underwrite`` decisions under the live
    ``ThresholdConfig`` and attach a proposal. Reads only the decision log."""
    from services.ai_threshold_config import get_threshold_config
    if decisions is None:
        from services.ai_decision_log import get_ai_decision_log
        decisions = get_ai_decision_log().all('underwrite')
    decisions = list(decisions)
    config = get_threshold_config()
    snapshot = config.export()
    live = {'approve': snapshot['default_approve'], 'reject': snapshot['default_reject']}
    samples, skipped = samples_from_decision_log(decisions, include_implicit=include_implicit)
    report = replay(samples, underwriting_scorer, live, agent_id='ai_automation_controller',
                    min_samples=min_samples, segment_thresholds=snapshot['segments'], skipped=skipped)
    payload = report.to_dict()
    payload['decisions_seen'] = len(decisions)
    payload['live_config'] = snapshot
    payload['proposal'] = propose_thresholds(samples, scorer=underwriting_scorer, current=live,
                                             target_precision=target_precision, min_samples=min_samples)
    return payload


def evaluate_claims_bot(assessment_records: Optional[Iterable[Dict[str, Any]]] = None,
                        *, min_labelled: Optional[int] = None) -> Dict[str, Any]:
    """The Claims Bot's authenticity calibration, reachable under one agent-eval
    surface. Delegates to ``calibrate_claims_thresholds`` so the existing
    ``/api/claims/bot-threshold-calibration`` report is unchanged."""
    from services.claims_bot_service import calibrate_claims_thresholds, CALIBRATION_MIN_LABELLED
    if assessment_records is None:
        assessment_records = _all_claims_fraud_records()
    kwargs = {'min_labelled': int(min_labelled)} if min_labelled is not None else {}
    report = calibrate_claims_thresholds(list(assessment_records), **kwargs)
    report['agent_id'] = 'claims_bot'
    report.setdefault('min_labelled', CALIBRATION_MIN_LABELLED)
    return report


def _all_claims_fraud_records() -> List[Dict[str, Any]]:
    from services.assessment_record_service import get_assessment_record_service
    svc = get_assessment_record_service()
    items: List[Dict[str, Any]] = []
    page = 1
    while page <= 100:
        chunk = svc.list_records(assessment_type='claims_fraud', page=page, page_size=200)
        rows = list(chunk.get('items') or [])
        if not rows:
            break
        items.extend(rows)
        if len(items) >= int(chunk.get('total') or 0):
            break
        page += 1
    return items


EVALUATORS: Dict[str, Callable[..., Dict[str, Any]]] = {
    'ai_automation_controller': evaluate_automation_controller,
    'claims_bot': evaluate_claims_bot,
}


def evaluate(agent_id: str, **kwargs: Any) -> Dict[str, Any]:
    """Dispatch to the agent's evaluator; ``KeyError`` for agents without one."""
    fn = EVALUATORS[agent_id]
    return fn(**kwargs)


# ---------------------------------------------------------------------------
# Golden sets
# ---------------------------------------------------------------------------

GoldenRunner = Callable[[Dict[str, Any]], Dict[str, Any]]
_GOLDEN_RUNNERS: Dict[str, GoldenRunner] = {}


def register_golden_runner(agent_id: str, runner: GoldenRunner) -> None:
    _GOLDEN_RUNNERS[agent_id] = runner


def golden_runners() -> Dict[str, GoldenRunner]:
    _ensure_default_runners()
    return dict(_GOLDEN_RUNNERS)


def default_fixtures_root() -> str:
    return os.environ.get(
        'PHINS_GOLDEN_DIR',
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tests', 'golden'),
    )


def _project(actual: Any, expected: Any, path: str, diffs: List[Dict[str, Any]]) -> None:
    """Compare ``actual`` against ``expected`` on the keys ``expected`` declares.

    Fixture authors list only the fields they want frozen; extra keys in the
    live output are allowed (additive changes never break a golden set, a
    changed value or a missing key does). Floats compare at 1e-6.
    """
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            diffs.append({'path': path, 'expected': expected, 'actual': actual})
            return
        for key, want in expected.items():
            if key not in actual:
                diffs.append({'path': f'{path}.{key}', 'expected': want, 'actual': '<missing>'})
                continue
            _project(actual[key], want, f'{path}.{key}', diffs)
        return
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            diffs.append({'path': path, 'expected': expected, 'actual': actual})
            return
        for i, (a, e) in enumerate(zip(actual, expected)):
            _project(a, e, f'{path}[{i}]', diffs)
        return
    if isinstance(expected, float) or isinstance(actual, float):
        try:
            if abs(float(actual) - float(expected)) <= 1e-6:
                return
        except (TypeError, ValueError):
            pass
        diffs.append({'path': path, 'expected': expected, 'actual': actual})
        return
    if actual != expected:
        diffs.append({'path': path, 'expected': expected, 'actual': actual})


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, sort_keys=True))


def run_golden(agent_id: str, fixtures_dir: Optional[str] = None,
               runner: Optional[GoldenRunner] = None, *, update: bool = False) -> Dict[str, Any]:
    """Execute ``tests/golden/<agent_id>/*.json`` and diff against ``expected``.

    Fixture shape::

        {"name": "...", "input": {...}, "expected": {...}}

    ``update=True`` rewrites each fixture's ``expected`` from the live output
    (an intentional, reviewed change) and reports it as ``updated``.
    """
    runner = runner or golden_runners().get(agent_id)
    if runner is None:
        raise KeyError(f'no golden runner registered for {agent_id!r}')
    directory = fixtures_dir or os.path.join(default_fixtures_root(), agent_id)
    files = sorted(glob.glob(os.path.join(directory, '*.json')))
    cases: List[Dict[str, Any]] = []
    passed = failed = updated = errored = 0
    for path in files:
        with open(path, 'r', encoding='utf-8') as fh:
            fixture = json.load(fh)
        name = fixture.get('name') or os.path.splitext(os.path.basename(path))[0]
        case: Dict[str, Any] = {'name': name, 'file': os.path.relpath(path, directory)}
        try:
            actual = _jsonable(runner(dict(fixture.get('input') or {})))
        except Exception as exc:  # noqa: BLE001 - one broken case must not hide the others
            errored += 1
            case.update(status='error', error=f'{type(exc).__name__}: {exc}')
            cases.append(case)
            continue
        if update:
            fixture['expected'] = actual if not fixture.get('expected') else _refresh(fixture['expected'], actual)
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(fixture, fh, indent=2, ensure_ascii=False, sort_keys=True)
                fh.write('\n')
            updated += 1
            case['status'] = 'updated'
            cases.append(case)
            continue
        diffs: List[Dict[str, Any]] = []
        _project(actual, fixture.get('expected') or {}, '$', diffs)
        if diffs:
            failed += 1
            case.update(status='failed', diffs=diffs)
        else:
            passed += 1
            case['status'] = 'passed'
        cases.append(case)
    return {
        'agent_id': agent_id,
        'fixtures_dir': directory,
        'total': len(files),
        'passed': passed,
        'failed': failed,
        'errored': errored,
        'updated': updated,
        'ok': failed == 0 and errored == 0,
        'cases': cases,
        'generated_at': _utc_now_iso(),
    }


def _refresh(expected: Any, actual: Any) -> Any:
    """Keep the fixture's key selection, take the live values (``--update``)."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        return {k: _refresh(v, actual.get(k)) for k, v in expected.items() if k in actual}
    if isinstance(expected, list) and isinstance(actual, list) and len(expected) == len(actual):
        return [_refresh(e, a) for e, a in zip(expected, actual)]
    return actual


def run_all_golden(fixtures_root: Optional[str] = None, *, update: bool = False) -> Dict[str, Any]:
    root = fixtures_root or default_fixtures_root()
    reports = {}
    for agent_id in sorted(golden_runners()):
        directory = os.path.join(root, agent_id)
        if not os.path.isdir(directory):
            continue
        reports[agent_id] = run_golden(agent_id, directory, update=update)
    return {
        'fixtures_root': root,
        'agents': reports,
        'ok': all(r['ok'] for r in reports.values()),
        'total': sum(r['total'] for r in reports.values()),
        'failed': sum(r['failed'] + r['errored'] for r in reports.values()),
    }


# -- default runners ---------------------------------------------------------

def _run_controller_underwrite(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Golden runner for the controller: one application → decision + details.

    Uses a fresh controller so a fixture never sees promoted thresholds or
    metrics from the live singleton; the decision log entry it writes is the
    same append-only record production writes.
    """
    from ai_automation_controller import AIAutomationController
    controller = AIAutomationController()
    decision, details = controller.auto_underwrite(dict(payload))
    details = {k: v for k, v in details.items() if k != 'decision_id'}
    return {'decision': decision.value, **details}


def _run_assessment_narrative(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Golden runner for Assessment AI: deterministic narrative over an
    analysis payload (the live LLM path is never used in a golden run)."""
    from services.assessment_ai_service import AssessmentAIService
    previous = os.environ.get('PHINS_ASSESSMENT_AI_ENABLED')
    os.environ['PHINS_ASSESSMENT_AI_ENABLED'] = 'false'
    try:
        service = AssessmentAIService()
        narrative = service.generate_narrative(
            dict(payload.get('analysis') or {}),
            customer_id=str(payload.get('customer_id') or 'GOLDEN'),
            options=payload.get('options'),
        )
    finally:
        if previous is None:
            os.environ.pop('PHINS_ASSESSMENT_AI_ENABLED', None)
        else:
            os.environ['PHINS_ASSESSMENT_AI_ENABLED'] = previous
    return {k: v for k, v in narrative.items() if k != 'generated_at'}


def _ensure_default_runners() -> None:
    _GOLDEN_RUNNERS.setdefault('ai_automation_controller', _run_controller_underwrite)
    _GOLDEN_RUNNERS.setdefault('assessment_ai', _run_assessment_narrative)


__all__ = [
    'APPROVE', 'REJECT', 'REVIEW', 'LABELS',
    'LabelledSample', 'SegmentReport', 'EvalReport', 'ClassMetrics',
    'normalise_label', 'underwriting_scorer', 'samples_from_decision_log',
    'confusion_counts', 'score_segment', 'replay', 'propose_thresholds',
    'evaluate', 'evaluate_automation_controller', 'evaluate_claims_bot', 'EVALUATORS',
    'run_golden', 'run_all_golden', 'register_golden_runner', 'golden_runners',
    'default_fixtures_root',
]
