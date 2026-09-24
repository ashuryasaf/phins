"""Age × ADL acceptance ledger for the portfolio simulator.

The matrix is a second view of the same lives the simulator already counts.
These tests pin the identities that view must satisfy.
"""

import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.actuarial_service import (
    ActuarialTablesStore,
    PortfolioSimulator,
    SimulationParams,
    finalize_age_adl_matrix,
)


def _run(count=400, **overrides):
    random.seed(7)
    store = ActuarialTablesStore()
    fields = dict(customer_count=count, age_min=18, age_max=70, age_mean=40, age_std=12)
    fields.update(overrides)
    params = SimulationParams(**fields)
    return PortfolioSimulator(store).generate_portfolio(params)


def test_matrix_reconciles_to_portfolio_and_demographics():
    result = _run()
    matrix = result['age_adl_matrix']
    summary = result['portfolio_summary']
    totals = matrix['totals']

    assert matrix['integrity']['all_checks_pass'] is True
    assert totals['applied'] == summary['requested_customers']
    assert totals['accepted'] == summary['accepted_customers']
    assert totals['rejected'] == result['declined']['count']
    assert totals['applied'] == totals['accepted'] + totals['rejected']

    accepted_by_band = {}
    accepted_by_adl = {}
    for band in matrix['bands']:
        assert band['applied'] == band['accepted'] + band['rejected']
        accepted_by_band[band['age_band']] = accepted_by_band.get(band['age_band'], 0) + band['accepted']
        for level, cell in band['by_adl'].items():
            assert cell['applied'] == cell['accepted'] + cell['rejected']
            accepted_by_adl[int(level)] = accepted_by_adl.get(int(level), 0) + cell['accepted']

    for label, count in result['demographics']['age_distribution'].items():
        assert accepted_by_band.get(label, 0) == count
    for level, count in result['demographics']['adl_distribution'].items():
        assert accepted_by_adl.get(int(level), 0) == count


def test_rejections_are_only_the_declined_adl_cells():
    random.seed(7)
    store = ActuarialTablesStore()
    store.config.decline_threshold = 7
    params = SimulationParams(customer_count=800, age_min=18, age_max=70, age_mean=40, age_std=12)
    result = PortfolioSimulator(store).generate_portfolio(params)
    assert result['declined']['count'] > 0
    matrix = result['age_adl_matrix']
    threshold = matrix['decline_threshold']
    rejected_sum = 0
    for row in matrix['rejected']:
        assert row['adl'] >= threshold
        assert row['rejected'] == row['applied']
        assert row['accepted'] == 0
        rejected_sum += row['rejected']
        for band in matrix['bands']:
            if band['age_band'] != row['age_band']:
                continue
            cell = band['by_adl'][str(row['adl'])]
            assert cell['accepted'] == 0
            assert cell['rejected'] == row['rejected']
    assert rejected_sum == result['declined']['count']
    assert rejected_sum == matrix['totals']['rejected']


def test_histogram_and_fitted_curve_describe_the_same_lives():
    result = _run(count=500, age_distribution='normal')
    dist = result['age_adl_matrix']['distribution']
    hist = dist['histogram']
    assert sum(row['applied'] for row in hist) == result['portfolio_summary']['requested_customers']
    assert sum(row['accepted'] for row in hist) == result['portfolio_summary']['accepted_customers']
    assert sum(row['rejected'] for row in hist) == result['declined']['count']
    assert dist['sample']['n'] == len_applied(hist)
    assert dist['parameters']['age_min'] <= dist['sample']['min'] <= dist['sample']['max'] <= dist['parameters']['age_max']
    assert abs(dist['sample']['mean'] - weighted_mean(hist)) < 1e-6
    ages = {point['age'] for point in dist['normal_curve']}
    assert ages == {row['age'] for row in hist}
    # The curve is a description of this sample, so its mass on the plotted
    # ages stays in the same order of magnitude as the applicant count.
    assert dist['curve_mass_on_plotted_ages'] > 0
    assert dist['curve_mass_on_plotted_ages'] < dist['sample']['n'] * 1.05


def test_uniform_draw_still_reconciles():
    result = _run(count=300, age_distribution='uniform', age_min=21, age_max=29)
    matrix = result['age_adl_matrix']
    assert matrix['integrity']['all_checks_pass'] is True
    assert matrix['distribution']['generating_model'] == 'uniform'
    assert {band['age_band'] for band in matrix['bands']} <= {'20-29'}
    assert matrix['distribution']['sample']['min'] >= 21
    assert matrix['distribution']['sample']['max'] <= 29


def test_finalize_flags_a_broken_cell():
    matrix = finalize_age_adl_matrix(
        {('20-29', 1): {'applied': 5, 'accepted': 4, 'rejected': 0}},
        {25: {'applied': 5, 'accepted': 4, 'rejected': 0}},
        requested_customers=5,
        accepted_customers=4,
        declined_count=1,
        decline_threshold=9,
        age_distribution_accepted={'20-29': 4},
        adl_distribution_accepted={1: 4},
        age_distribution='normal',
        age_mean=25,
        age_std=2,
        age_min=21,
        age_max=29,
    )
    assert matrix['integrity']['all_checks_pass'] is False
    assert matrix['integrity']['checks']['accepted_plus_rejected_equals_applied'] is False


def len_applied(hist):
    return sum(row['applied'] for row in hist)


def weighted_mean(hist):
    n = len_applied(hist)
    return sum(row['age'] * row['applied'] for row in hist) / n


@pytest.mark.parametrize('count', [50, 200])
def test_acceptance_columns_exclude_rejections(count):
    result = _run(count=count)
    matrix = result['age_adl_matrix']
    accepted_cells = 0
    for band in matrix['bands']:
        accepted_cells += sum(cell['accepted'] for cell in band['by_adl'].values())
    assert accepted_cells == matrix['totals']['accepted']
    assert accepted_cells == result['portfolio_summary']['accepted_customers']
