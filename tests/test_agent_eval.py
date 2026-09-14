"""A6 evaluation harness: replay metrics, minimum-sample guard, monotone
proposals, golden-set runner, ThresholdConfig snapshots, and the admin
eval / promote routes (dispatcher-level and over HTTP)."""

import json
import os
import sys
from datetime import datetime, timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for entry in (ROOT, os.path.join(ROOT, 'web_portal')):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from services import agent_eval  # noqa: E402
from services.agent_eval import (  # noqa: E402
    APPROVE, REJECT, REVIEW, LabelledSample, replay, propose_thresholds,
    samples_from_decision_log, underwriting_scorer, run_golden,
)
from services.ai_threshold_config import ThresholdConfig, get_threshold_config  # noqa: E402
from services.ai_decision_log import get_ai_decision_log  # noqa: E402


@pytest.fixture
def restore_threshold_config():
    config = get_threshold_config()
    snapshot = config.export()
    yield config
    config.import_(snapshot)


@pytest.fixture
def clean_decision_log():
    log = get_ai_decision_log()
    log.clear()
    yield log
    log.clear()


def _samples(scores_labels, segment='global', explicit=True):
    return [LabelledSample(score=s, label=l, segment=segment, recorded=None, explicit=explicit)
            for s, l in scores_labels]


# ---------------------------------------------------------------------------
# replay
# ---------------------------------------------------------------------------

def test_replay_yields_known_precision_recall_and_confusion():
    # approve threshold 0.8, reject 0.2.
    samples = _samples([
        (0.95, APPROVE), (0.90, APPROVE), (0.85, REJECT),   # 3 replay-approvals, 1 wrong
        (0.10, REJECT), (0.15, APPROVE),                    # 2 replay-rejects, 1 wrong
        (0.50, APPROVE), (0.60, REJECT),                    # 2 abstain to review
        (0.05, REJECT),                                     # correct reject
    ])
    report = replay(samples, underwriting_scorer, {'approve': 0.8, 'reject': 0.2}, min_samples=5)
    seg = report.overall
    assert seg.status == 'ok'
    assert seg.samples == 8
    assert seg.confusion[APPROVE] == {APPROVE: 2, REJECT: 1, REVIEW: 0}
    assert seg.confusion[REJECT] == {APPROVE: 1, REJECT: 2, REVIEW: 0}
    assert sum(seg.confusion[REVIEW].values()) == 2
    approve = seg.per_class[APPROVE]
    assert approve.precision == pytest.approx(2 / 3, abs=1e-4)
    assert approve.recall == pytest.approx(2 / 4, abs=1e-4)   # 4 approve labels in total
    reject = seg.per_class[REJECT]
    assert reject.precision == pytest.approx(2 / 3, abs=1e-4)
    assert reject.recall == pytest.approx(2 / 4, abs=1e-4)
    assert seg.agreement_rate == pytest.approx(4 / 6, abs=1e-4)
    assert seg.review_share == pytest.approx(2 / 8, abs=1e-4)
    assert seg.approved_but_rejected == 1 and seg.rejected_but_approved == 1
    payload = report.to_dict()
    assert payload['read_only'] is True
    assert payload['overall']['disagreement_cost'] == 2


def test_replay_min_sample_guard_and_per_segment_thresholds():
    small = _samples([(0.9, APPROVE), (0.1, REJECT)], segment='under_25|clerk')
    big = _samples([(0.9, APPROVE)] * 10 + [(0.1, REJECT)] * 10, segment='35_44|nurse')
    report = replay(small + big, underwriting_scorer, {'approve': 0.85, 'reject': 0.15},
                    min_samples=20, segment_thresholds={'35_44|nurse': {'approve': 0.95}})
    assert report.segments['under_25|clerk'].status == 'insufficient_data'
    nurse = report.segments['35_44|nurse']
    assert nurse.status == 'ok'
    # The promoted 0.95 cut-off sends every 0.9 to review for that segment only.
    assert nurse.thresholds['approve'] == 0.95
    assert sum(nurse.confusion[REVIEW].values()) == 10
    assert report.overall.thresholds['approve'] == 0.85
    assert sum(report.overall.confusion[REVIEW].values()) == 0
    assert replay([], underwriting_scorer, {'approve': 0.85, 'reject': 0.15}).overall.status == 'empty'


def test_override_rate_counts_explicit_disagreement_only():
    samples = [
        LabelledSample(0.9, REJECT, recorded=APPROVE, explicit=True),   # human overturned
        LabelledSample(0.9, APPROVE, recorded=APPROVE, explicit=True),  # human confirmed
        LabelledSample(0.9, APPROVE, recorded=APPROVE, explicit=False), # silence
        LabelledSample(0.1, REJECT, recorded=REJECT, explicit=False),
    ]
    seg = replay(samples, underwriting_scorer, {'approve': 0.85, 'reject': 0.15}, min_samples=1).overall
    assert seg.explicit_labels == 2 and seg.implicit_labels == 2
    assert seg.override_rate == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# samples_from_decision_log
# ---------------------------------------------------------------------------

def test_samples_from_decision_log_maps_explicit_implicit_and_skips():
    decisions = [
        {'decision_type': 'underwrite', 'segment': 's', 'output': {'decision': 'auto_approve', 'risk_score': 0.9},
         'human_override': 'rejected', 'decision_id': 'D1'},
        {'decision_type': 'underwrite', 'segment': 's', 'output': {'decision': 'auto_approve', 'risk_score': 0.9},
         'human_override': None},
        {'decision_type': 'underwrite', 'segment': 's', 'output': {'decision': 'human_review', 'risk_score': 0.5},
         'human_override': None},
        {'decision_type': 'underwrite', 'segment': 's', 'output': {'decision': 'human_review', 'risk_score': 0.5},
         'human_override': 'approve_with_conditions'},
        {'decision_type': 'underwrite', 'segment': 's', 'output': {'decision': 'auto_reject'},
         'human_override': None},
        {'decision_type': 'underwrite', 'segment': 's', 'output': {'decision': 'auto_approve', 'risk_score': 0.9},
         'human_override': 'escalated to legal'},
        {'decision_type': 'quote', 'output': {'decision': 'quoted', 'risk_score': 0.9}},
    ]
    samples, skipped = samples_from_decision_log(decisions)
    labels = [(s.label, s.explicit, s.recorded) for s in samples]
    assert labels == [
        (REJECT, True, APPROVE),
        (APPROVE, False, APPROVE),
        (APPROVE, True, REVIEW),
    ]
    assert samples[0].decision_id == 'D1'
    assert skipped == {'wrong_type': 1, 'no_score': 1, 'unlabelled': 1, 'unmapped_override': 1}
    only_explicit, _ = samples_from_decision_log(decisions, include_implicit=False)
    assert all(s.explicit for s in only_explicit) and len(only_explicit) == 2


# ---------------------------------------------------------------------------
# propose_thresholds
# ---------------------------------------------------------------------------

def _calibration_set():
    # Human approves everything >= 0.8 and rejects everything <= 0.25, with
    # one noisy approval at 0.7 and one noisy rejection at 0.3.
    rows = []
    for s in (0.95, 0.9, 0.85, 0.8):
        rows += [(s, APPROVE)] * 5
    rows += [(0.75, REJECT)] * 3 + [(0.7, APPROVE)] * 2 + [(0.7, REJECT)] * 3
    for s in (0.05, 0.1, 0.15, 0.2, 0.25):
        rows += [(s, REJECT)] * 4
    rows += [(0.3, REJECT)] * 2 + [(0.3, APPROVE)] * 3
    return _samples(rows)


def test_propose_thresholds_is_monotone_in_target_precision_and_never_promotes(restore_threshold_config):
    samples = _calibration_set()
    before = restore_threshold_config.export()
    picks = []
    for target in (0.6, 0.75, 0.9, 0.99, 1.0):
        out = propose_thresholds(samples, current={'approve': 0.85, 'reject': 0.15},
                                 target_precision=target, min_samples=10)
        seg = out['proposals']['global']
        assert seg['status'] in ('recommended', 'partial', 'target_unreachable')
        assert seg['reject'] < seg['approve']
        picks.append((target, seg['approve'], seg['reject'], seg['approve_precision'], seg['reject_precision']))
    for (_, a1, r1, _, _), (_, a2, r2, _, _) in zip(picks, picks[1:]):
        assert a2 >= a1, picks
        assert r2 <= r1, picks
    # At a reachable target the pick is the most automated grid point meeting it.
    lenient = propose_thresholds(samples, target_precision=0.6, min_samples=10)['proposals']['global']
    assert lenient['approve'] <= 0.75 and lenient['approve_precision'] >= 0.6
    strict = propose_thresholds(samples, target_precision=1.0, min_samples=10)['proposals']['global']
    assert strict['approve'] == 0.8 and strict['approve_precision'] == 1.0
    assert strict['reject'] == 0.25 and strict['reject_precision'] == 1.0
    assert out['read_only'] is True
    assert restore_threshold_config.export() == before


def test_propose_thresholds_guard_and_validation():
    samples = _samples([(0.9, APPROVE)] * 5)
    out = propose_thresholds(samples, min_samples=20)
    assert out['proposals']['global']['status'] == 'insufficient_data'
    assert out['proposals']['global']['approve'] == 0.85
    with pytest.raises(ValueError):
        propose_thresholds(samples, target_precision=0)
    with pytest.raises(ValueError):
        propose_thresholds(samples, target_precision=1.5)


def test_propose_thresholds_reports_unreachable_target():
    # Humans reject everything the rules would approve: no approve cut-off works.
    samples = _samples([(0.95, REJECT)] * 12 + [(0.05, REJECT)] * 12)
    out = propose_thresholds(samples, target_precision=0.9, min_samples=10)['proposals']['global']
    assert out['status'] == 'target_unreachable'
    assert out['approve'] == 0.85          # current kept
    assert out['reject_precision'] == 1.0  # reject side still evaluated


# ---------------------------------------------------------------------------
# ThresholdConfig snapshots
# ---------------------------------------------------------------------------

def test_threshold_config_export_import_round_trip_and_validation():
    config = ThresholdConfig()
    config.promote('25_34|nurse', 0.9, 0.1)
    snap = config.export()
    snap['segments']['25_34|nurse']['approve'] = 0.5   # deep copy: live config untouched
    assert config.get('25_34|nurse') == (0.9, 0.1)
    other = ThresholdConfig()
    other.import_(config.export())
    assert other.export() == config.export()
    with pytest.raises(ValueError):
        other.import_({'segments': {'x': {'approve': 0.2, 'reject': 0.4}}})
    assert other.export() == config.export()   # all-or-nothing: nothing applied
    with pytest.raises(ValueError):
        other.import_({'default_approve': 0.1, 'default_reject': 0.5})


# ---------------------------------------------------------------------------
# evaluate_automation_controller over the real decision log
# ---------------------------------------------------------------------------

def test_evaluate_automation_controller_reads_log_and_promoted_segments(restore_threshold_config, clean_decision_log):
    from ai_automation_controller import AIAutomationController
    controller = AIAutomationController()
    ids = []
    for i in range(25):
        decision, details = controller.auto_underwrite({
            'application_id': f'APP-{i}', 'age': 30, 'occupation': 'nurse', 'smoker': False,
            'pre_existing_conditions': False, 'health_score': 9, 'employment_stable': True,
        })
        assert decision.value == 'auto_approve'
        ids.append(details.get('decision_id'))
    assert all(ids)
    # Reviewers overturned the first three approvals.
    for decision_id in ids[:3]:
        assert clean_decision_log.record_override(decision_id, 'rejected', 'audit', 'uw-lead')
    restore_threshold_config.promote('25_34|nurse', 0.99, 0.10)

    payload = agent_eval.evaluate_automation_controller(min_samples=20, target_precision=0.9)
    assert payload['agent_id'] == 'ai_automation_controller'
    assert payload['decisions_seen'] == 25
    seg = payload['segments']['25_34|nurse']
    assert seg['samples'] == 25 and seg['explicit_labels'] == 3 and seg['implicit_labels'] == 22
    assert seg['thresholds'] == {'approve': 0.99, 'reject': 0.10}
    assert seg['status'] == 'ok'
    assert payload['live_config']['segments']['25_34|nurse'] == {'approve': 0.99, 'reject': 0.10}
    assert payload['proposal']['proposals']['25_34|nurse']['samples'] == 25
    assert payload['read_only'] is True
    # Evaluation changed nothing.
    assert restore_threshold_config.get('25_34|nurse') == (0.99, 0.10)
    assert len(clean_decision_log.all('underwrite')) == 25


def test_evaluate_dispatch_unknown_agent():
    with pytest.raises(KeyError):
        agent_eval.evaluate('nonexistent_agent')
    assert set(agent_eval.EVALUATORS) >= {'ai_automation_controller', 'claims_bot'}


def test_evaluate_claims_bot_delegates_to_calibration():
    payload = agent_eval.evaluate_claims_bot([], min_labelled=5)
    assert payload['agent_id'] == 'claims_bot'
    assert payload['read_only'] is True and payload['insufficient_data'] is True
    assert payload['min_labelled'] == 5


# ---------------------------------------------------------------------------
# golden sets
# ---------------------------------------------------------------------------

def _write_fixture(directory, name, payload):
    path = os.path.join(directory, f'{name}.json')
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh)
    return path


def test_run_golden_pass_fail_error_and_update(tmp_path):
    fixtures = tmp_path / 'toy_agent'
    fixtures.mkdir()
    _write_fixture(fixtures, 'pass', {'input': {'x': 2}, 'expected': {'double': 4, 'nested': {'ok': True}}})
    _write_fixture(fixtures, 'fail', {'input': {'x': 3}, 'expected': {'double': 7}})
    _write_fixture(fixtures, 'missing_key', {'input': {'x': 1}, 'expected': {'double': 2, 'absent': 1}})
    _write_fixture(fixtures, 'boom', {'input': {'x': None}, 'expected': {}})

    def runner(payload):
        return {'double': payload['x'] * 2, 'nested': {'ok': True, 'extra': 'ignored'}, 'ts': 'now'}

    report = run_golden('toy_agent', str(fixtures), runner)
    by_name = {c['name']: c for c in report['cases']}
    assert report['total'] == 4 and report['passed'] == 1 and report['failed'] == 2 and report['errored'] == 1
    assert report['ok'] is False
    assert by_name['pass']['status'] == 'passed'
    assert by_name['fail']['diffs'] == [{'path': '$.double', 'expected': 7, 'actual': 6}]
    assert by_name['missing_key']['diffs'] == [{'path': '$.absent', 'expected': 1, 'actual': '<missing>'}]
    assert by_name['boom']['status'] == 'error' and 'TypeError' in by_name['boom']['error']

    # --update keeps each fixture's key selection and takes the live values.
    updated = run_golden('toy_agent', str(fixtures), runner, update=True)
    assert updated['updated'] == 3 and updated['errored'] == 1
    with open(fixtures / 'fail.json', encoding='utf-8') as fh:
        assert json.load(fh)['expected'] == {'double': 6}
    with open(fixtures / 'missing_key.json', encoding='utf-8') as fh:
        assert json.load(fh)['expected'] == {'double': 2}   # absent key dropped, ts never added
    rerun = run_golden('toy_agent', str(fixtures), runner)
    assert rerun['passed'] == 3 and rerun['failed'] == 0

    with pytest.raises(KeyError):
        run_golden('no_such_agent', str(fixtures))


def test_committed_golden_sets_pass():
    """The repo's own fixtures must agree with the live agents (CI gate)."""
    report = agent_eval.run_all_golden()
    assert report['total'] >= 2, report
    assert set(report['agents']) >= {'ai_automation_controller', 'assessment_ai'}
    assert report['ok'], json.dumps(report, indent=1, default=str)[:4000]


def test_golden_controller_runner_uses_a_fresh_controller(restore_threshold_config):
    restore_threshold_config.promote('25_34|nurse', 0.999, 0.1)
    out = agent_eval.golden_runners()['ai_automation_controller'](
        {'age': 30, 'occupation': 'nurse', 'health_score': 0.95, 'income': 90000, 'smoker': False})
    # The live singleton's promoted segment is visible to the fresh controller
    # only through the shared ThresholdConfig, which is what production reads.
    assert out['segment'] == '25_34|nurse'
    assert 'decision_id' not in out


# ---------------------------------------------------------------------------
# routes: dispatcher level
# ---------------------------------------------------------------------------

def _ext():
    import web_portal.api_extensions as ext
    return ext


def test_eval_route_authz_and_shapes(restore_threshold_config, clean_decision_log):
    ext = _ext()
    path = '/api/admin/ai-agents/eval/ai_automation_controller'
    assert ext.dispatch_get(path, None, {}, '127.0.0.1')[0] == 401
    status, body = ext.dispatch_get(path, {'role': 'customer'}, {}, '127.0.0.1')
    assert status == 403 and 'error' in body
    status, body = ext.dispatch_get('/api/admin/ai-agents/eval/nope', {'role': 'actuary'}, {}, '127.0.0.1')
    assert status == 404 and 'available' in body
    status, body = ext.dispatch_get(path, {'role': 'actuary'}, {'min_samples': ['abc']}, '127.0.0.1')
    assert status == 400
    status, body = ext.dispatch_get(path, {'role': 'actuary'},
                                    {'min_samples': ['5'], 'target_precision': ['0.9'], 'implicit': ['false']},
                                    '127.0.0.1')
    assert status == 200 and body['success'] is True
    ev = body['evaluation']
    assert ev['agent_id'] == 'ai_automation_controller' and ev['min_samples'] == 5
    assert ev['proposal']['target_precision'] == 0.9
    status, body = ext.dispatch_get('/api/admin/ai-agents/eval/claims_bot', {'role': 'admin'}, {}, '127.0.0.1')
    assert status == 200 and body['evaluation']['agent_id'] == 'claims_bot'


def test_promote_route_validates_audits_and_is_admin_only(restore_threshold_config, clean_decision_log):
    ext = _ext()
    path = ext.AI_AGENTS_PROMOTE_PATH
    good = {'segment': '35_44|teacher', 'approve': 0.9, 'reject': 0.1, 'reason': 'eval 2026-09 P=0.97'}
    assert ext.dispatch_post(path, None, good, '127.0.0.1')[0] == 401
    status, body = ext.dispatch_post(path, {'role': 'actuary', 'username': 'act'}, good, '127.0.0.1')
    assert status == 403 and 'error' in body
    admin = {'role': 'admin', 'username': 'ops-admin'}
    for bad in (
        {**good, 'segment': ''},
        {**good, 'approve': 'x'},
        {**good, 'approve': 1.2},
        {**good, 'reject': 0.95},
        {**good, 'reason': ''},
    ):
        status, body = ext.dispatch_post(path, admin, bad, '127.0.0.1')
        assert status == 400 and 'error' in body, bad
    assert restore_threshold_config.get('35_44|teacher') == (0.85, 0.15)   # nothing applied

    status, body = ext.dispatch_post(path, admin, good, '127.0.0.1')
    assert status == 200 and body['success'] is True
    assert body['before'] == {'approve': 0.85, 'reject': 0.15, 'source': 'default'}
    assert body['after'] == {'approve': 0.9, 'reject': 0.1}
    assert restore_threshold_config.get('35_44|teacher') == (0.9, 0.1)
    # Append-only decision-log record with before/after.
    rec = clean_decision_log.get(body['decision_id'])
    assert rec['decision_type'] == 'threshold_promotion' and rec['segment'] == '35_44|teacher'
    assert rec['inputs']['before'] == body['before'] and rec['output']['after'] == body['after']
    assert rec['inputs']['reason'] == good['reason']
    # Portal audit row (in-memory AuditService when the server module is loaded).
    import web_portal.server as portal
    events = [e for e in portal.audit._events if e['action'] == 'ai_threshold_promoted']
    assert events and events[-1]['details']['segment'] == '35_44|teacher'
    assert events[-1]['details']['before'] == body['before']
    assert events[-1]['details']['promoted_by'] == 'ops-admin'
    assert body['audit_id'] == events[-1]['id']

    # A second promotion records the previous promoted values as "before".
    status, body = ext.dispatch_post(path, admin, {**good, 'approve': 0.92}, '127.0.0.1')
    assert status == 200 and body['before'] == {'approve': 0.9, 'reject': 0.1}


def test_promote_rolls_back_when_decision_log_record_fails(restore_threshold_config, clean_decision_log, monkeypatch):
    ext = _ext()
    monkeypatch.setattr(clean_decision_log, 'record', lambda *a, **k: '')
    status, body = ext.dispatch_post(ext.AI_AGENTS_PROMOTE_PATH, {'role': 'admin', 'username': 'a'},
                                     {'segment': 'x|y', 'approve': 0.9, 'reject': 0.1, 'reason': 'r'}, '127.0.0.1')
    assert status == 503 and 'rolled back' in body['error']
    assert 'x|y' not in restore_threshold_config.export()['segments']


# ---------------------------------------------------------------------------
# routes: over HTTP (POST forwarding into api_extensions)
# ---------------------------------------------------------------------------

def _base_url():
    return os.environ.get('TEST_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')


def _http(method, path, token=None, body=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = Request(_base_url() + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode('utf-8') or '{}')


def _seed_session(portal, token, role):
    expires = (datetime.now() + timedelta(hours=1)).isoformat()
    with portal.STATE_LOCK:
        portal.SESSIONS[token] = {'username': f'{role}-eval', 'role': role, 'expires': expires,
                                  'jti': f'{token}-jti'}


def test_eval_and_promote_over_http(restore_threshold_config, clean_decision_log):
    import web_portal.server as portal
    # First unauthenticated request lets the embedded server reset per-port state.
    status, _ = _http('GET', '/api/admin/ai-agents/eval/ai_automation_controller')
    assert status == 401
    _seed_session(portal, 'phins_eval_actuary', 'actuary')
    _seed_session(portal, 'phins_eval_admin', 'admin')
    try:
        status, body = _http('GET', '/api/admin/ai-agents/eval/ai_automation_controller?min_samples=3',
                             token='phins_eval_actuary')
        assert status == 200 and body['evaluation']['min_samples'] == 3

        promote = {'segment': '45_54|pilot', 'approve': 0.93, 'reject': 0.07, 'reason': 'http test'}
        status, body = _http('POST', '/api/admin/ai-agents/thresholds/promote',
                             token='phins_eval_actuary', body=promote)
        assert status == 403 and 'error' in body
        status, body = _http('POST', '/api/admin/ai-agents/thresholds/promote',
                             token='phins_eval_admin', body=promote)
        assert status == 200, body
        assert body['after'] == {'approve': 0.93, 'reject': 0.07}
        assert get_threshold_config().get('45_54|pilot') == (0.93, 0.07)
        assert get_ai_decision_log().get(body['decision_id'])['decision_type'] == 'threshold_promotion'
    finally:
        with portal.STATE_LOCK:
            portal.SESSIONS.pop('phins_eval_actuary', None)
            portal.SESSIONS.pop('phins_eval_admin', None)
