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
    # P2/P3 units not started.
    for uid in ('U8', 'U9', 'U10', 'U11', 'U12'):
        assert by_id[uid]['status'] == 'missing', (uid, by_id[uid])


def test_scorecard_uses_explicit_repo_root(tmp_path: Path):
    empty = compute_integrity_scorecard(repo_root=str(tmp_path))
    assert empty['claimed_score'] == BASELINE_SCORE
    assert empty['plan_present'] is False
    assert all(u['status'] == 'missing' for u in empty['units'])
