"""ERP/MGA integrity 1–100 scorecard — review gate for the plan bands."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.erp.integrity_scorecard import (
    BASELINE_SCORE,
    BANDS,
    compute_integrity_scorecard,
    render_scorecard_markdown,
)


def test_scorecard_schema_and_bounds():
    report = compute_integrity_scorecard()
    assert report['schema'] == 'phins.erp_integrity_scorecard.v1'
    assert report['baseline_score'] == BASELINE_SCORE
    assert report['target_score'] == 100
    assert 1 <= report['claimed_score'] <= 100
    assert 1.0 <= float(report['progress_score']) <= 100.0
    assert report['plan_present'] is True
    assert len(report['units']) == 14
    assert len(report['bands']) == 4
    assert {b['id'] for b in report['bands']} == {'P0', 'P1', 'P2', 'P3'}


def test_band_points_sum_to_forty_two():
    assert sum(int(b['points']) for b in BANDS) == 42
    assert BASELINE_SCORE + 42 == 100


def test_claimed_score_requires_full_band():
    """Partial units must not claim band points (plan rule)."""
    report = compute_integrity_scorecard()
    claimed = int(report['claimed_points'])
    # Recompute from band rows.
    expected = sum(int(b['points']) for b in report['bands'] if b['claimed'])
    assert claimed == expected
    assert report['claimed_score'] == BASELINE_SCORE + claimed


def test_progress_score_ge_claimed():
    report = compute_integrity_scorecard()
    assert float(report['progress_score']) + 1e-9 >= float(report['claimed_score'])


def test_markdown_render_includes_scores():
    report = compute_integrity_scorecard()
    md = render_scorecard_markdown(report)
    assert 'Claimed score' in md
    assert str(report['claimed_score']) in md
    assert 'U1' in md and 'U14' in md


def test_known_landed_units_on_this_checkout():
    """U1/U3/U4/U5 are expected on the integrity track tip used for review."""
    report = compute_integrity_scorecard()
    by_id = {u['unit_id']: u for u in report['units']}
    for uid in ('U1', 'U3', 'U4', 'U5'):
        assert by_id[uid]['status'] == 'landed', (uid, by_id[uid])
    # U6 must not take half credit from the U4 job's forward-looking docstring.
    assert by_id['U6']['status'] == 'missing', by_id['U6']
    assert by_id['U7']['status'] == 'missing', by_id['U7']
    # P2/P3 units not started — baseline snapshot/queue/tenant files alone
    # must not inflate U13/U14 progress.
    for uid in ('U8', 'U9', 'U10', 'U11', 'U12', 'U13', 'U14'):
        assert by_id[uid]['status'] == 'missing', (uid, by_id[uid])


def test_scorecard_uses_explicit_repo_root(tmp_path: Path):
    empty = compute_integrity_scorecard(repo_root=str(tmp_path))
    assert empty['claimed_score'] == BASELINE_SCORE
    assert empty['plan_present'] is False
    assert all(u['status'] == 'missing' for u in empty['units'])


def test_u6_ignores_forward_looking_docstring(tmp_path: Path):
    """A U4 job that only *mentions* finance.books_tied is not U6 progress."""
    job = tmp_path / 'services' / 'jobs'
    job.mkdir(parents=True)
    (job / 'books_integrity_job.py').write_text(
        '"""agent_artifact later in U6 for the daily finance.books_tied cert)."""\n',
        encoding='utf-8',
    )
    report = compute_integrity_scorecard(repo_root=str(tmp_path))
    by_id = {u['unit_id']: u for u in report['units']}
    assert by_id['U6']['status'] == 'missing'


def test_module_check_respects_repo_root(tmp_path: Path):
    """U6 landed evidence must come from the scored tree, not sys.path."""
    from services.erp import integrity_scorecard as sc

    # Live checkout may later grow books_tied; an empty root must stay missing.
    assert sc._module_under_root(tmp_path, 'services.erp.books_tied') is False
    pkg = tmp_path / 'services' / 'erp'
    pkg.mkdir(parents=True)
    (pkg / 'books_tied.py').write_text('CERTIFICATE = True\n', encoding='utf-8')
    assert sc._module_under_root(tmp_path, 'services.erp.books_tied') is True
    report = compute_integrity_scorecard(repo_root=str(tmp_path))
    by_id = {u['unit_id']: u for u in report['units']}
    assert by_id['U6']['status'] == 'partial'  # module without test


def test_u14_baseline_snapshot_files_are_not_partial(tmp_path: Path):
    """Baseline ledger_snapshot_store + job queue alone must not credit U14."""
    for rel in (
        'services/ledger_snapshot_store.py',
        'services/agent_job_queue.py',
    ):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# baseline\n', encoding='utf-8')
    report = compute_integrity_scorecard(repo_root=str(tmp_path))
    by_id = {u['unit_id']: u for u in report['units']}
    assert by_id['U14']['status'] == 'missing'


def test_u13_baseline_tenant_tests_are_not_partial(tmp_path: Path):
    """Customer cross-tenant tests without binder_id are not U13 progress."""
    path = tmp_path / 'tests' / 'test_tenant_isolation.py'
    path.parent.mkdir(parents=True)
    path.write_text('def test_cross_tenant():\n    assert True\n', encoding='utf-8')
    models = tmp_path / 'database' / 'models.py'
    models.parent.mkdir(parents=True)
    models.write_text('class Policy:\n    pass\n', encoding='utf-8')
    report = compute_integrity_scorecard(repo_root=str(tmp_path))
    by_id = {u['unit_id']: u for u in report['units']}
    assert by_id['U13']['status'] == 'missing'


def test_u7_ignores_baseline_clawback_mentions(tmp_path: Path):
    """A clawback TODO in agent_ecosystem_service is not U7 progress."""
    path = tmp_path / 'services' / 'agent_ecosystem_service.py'
    path.parent.mkdir(parents=True)
    path.write_text('# TODO: commission clawback on lapse\n', encoding='utf-8')
    report = compute_integrity_scorecard(repo_root=str(tmp_path))
    by_id = {u['unit_id']: u for u in report['units']}
    assert by_id['U7']['status'] == 'missing'
