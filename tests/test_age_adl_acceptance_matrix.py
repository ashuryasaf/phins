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
    MAX_ACCEPTANCE_AGE,
    ActuarialTablesStore,
    PortfolioSimulator,
    SimulationParams,
    finalize_age_adl_matrix,
    sample_simulation_age,
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
    # Stay inside the acceptance cap so every rejection in this test is an
    # ADL decline. Ages past the cap are covered separately.
    params = SimulationParams(customer_count=800, age_min=18, age_max=MAX_ACCEPTANCE_AGE, age_mean=40, age_std=12)
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


@pytest.mark.parametrize('age_max', [42, 50, 55])
def test_normal_draw_does_not_pile_acceptances_on_maximum_age(age_max):
    """The maximum age used to absorb the whole right-hand tail.

    Whatever Maximum Age was chosen, that single year then showed far more
    lives (and, while it was still inside the acceptance cap, far more
    acceptances) than the year beside it.
    """
    random.seed(20260927 + age_max)
    counts = {}
    for _ in range(6000):
        age = sample_simulation_age(18, age_max, 35.0, 12.0, 'normal')
        counts[age] = counts.get(age, 0) + 1
    assert min(counts) >= 18
    assert max(counts) <= age_max
    boundary = counts[age_max]
    previous = counts[age_max - 1]
    assert previous > 0
    assert boundary < previous * 2


def test_simulation_declines_ages_above_65_when_maximum_age_is_higher():
    random.seed(11)
    store = ActuarialTablesStore()
    params = SimulationParams(
        customer_count=2500,
        age_min=40,
        age_max=80,
        age_mean=62,
        age_std=8,
        age_distribution='normal',
    )
    result = PortfolioSimulator(store).generate_portfolio(params)
    matrix = result['age_adl_matrix']
    hist = matrix['distribution']['histogram']
    older = [row for row in hist if row['age'] > MAX_ACCEPTANCE_AGE]

    assert matrix['max_acceptance_age'] == MAX_ACCEPTANCE_AGE == 65
    assert matrix['integrity']['all_checks_pass'] is True
    assert older, 'the draw window extends past 65, so some applicants must be older'
    assert all(row['accepted'] == 0 and row['rejected'] == row['applied'] for row in older)
    assert all(row['accepted'] == 0 or row['age'] <= MAX_ACCEPTANCE_AGE for row in hist)
    assert max(row['age'] for row in hist if row['accepted']) <= MAX_ACCEPTANCE_AGE

    reason = f'Age exceeds maximum acceptance age {MAX_ACCEPTANCE_AGE}'
    assert result['declined']['reasons'][reason] == sum(row['applied'] for row in older)
    assert result['portfolio_summary']['accepted_customers'] == sum(row['accepted'] for row in hist)
    assert result['portfolio_summary']['accepted_customers'] + result['declined']['count'] == 2500
    assert result['premium_reconciliation']['all_identities_pass'] is True

    by_age = {row['age']: row for row in hist}
    # Age 80 must not be a dump of everyone the normal draw wanted to place past it.
    if by_age.get(79, {}).get('applied', 0) > 0:
        assert by_age[80]['applied'] < by_age[79]['applied'] * 2.5
    assert by_age.get(80, {}).get('accepted', 0) == 0


def test_window_entirely_above_acceptance_age_accepts_nobody():
    random.seed(3)
    params = SimulationParams(
        customer_count=180,
        age_min=70,
        age_max=85,
        age_mean=76,
        age_std=3,
        age_distribution='normal',
    )
    result = PortfolioSimulator(ActuarialTablesStore()).generate_portfolio(params)
    summary = result['portfolio_summary']
    matrix = result['age_adl_matrix']
    assert summary['accepted_customers'] == 0
    assert summary['total_annual_premium'] == 0
    assert result['declined']['count'] == 180
    assert matrix['integrity']['all_checks_pass'] is True
    assert all(row['accepted'] == 0 for row in matrix['distribution']['histogram'])
    assert result['premium_reconciliation']['all_identities_pass'] is True


@pytest.mark.parametrize('count', [50, 200])
def test_acceptance_columns_exclude_rejections(count):
    result = _run(count=count)
    matrix = result['age_adl_matrix']
    accepted_cells = 0
    for band in matrix['bands']:
        accepted_cells += sum(cell['accepted'] for cell in band['by_adl'].values())
    assert accepted_cells == matrix['totals']['accepted']
    assert accepted_cells == result['portfolio_summary']['accepted_customers']
