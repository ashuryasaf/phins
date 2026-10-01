"""PhinSafe rider: one fifth of each parent policy, sliced from the simulator."""

from __future__ import annotations

import json
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from services.actuarial_service import SimulationParams, get_portfolio_simulator
from services.phinsafe_rider import (
    BENEFIT_DENOMINATOR,
    PhinSafeIntegrityError,
    anchor_book,
    anchor_rider,
    bind_rider,
    open_claim,
    project_book,
)
from services.process_pipeline_orchestrator import ProcessPipelineOrchestrator


class _Ledger:
    def __init__(self):
        self.transaction_ledger = {}
        self.events = []

    def append_event(self, **kwargs):
        entry_id = kwargs['entry_id']
        if entry_id in self.transaction_ledger:
            return self.transaction_ledger[entry_id]
        entry = {
            'id': entry_id,
            'entry_hash': f"hash-{len(self.events) + 1}",
            'sequence_no': len(self.events) + 1,
            **kwargs,
        }
        self.transaction_ledger[entry_id] = entry
        self.events.append(entry)
        return entry


def _snapshot():
    rows = [
        {
            'age': 10, 'accepted': 1, 'term_years': 20,
            'coverage': 100000, 'annual_premium': 1000, 'risk_premium': 800,
            'savings_premium': 100, 'pv_mortality': 200, 'pv_disability': 100,
            'expected_claims_year1': 30,
        },
        {
            'age': 30, 'accepted': 4, 'term_years': 80,
            'coverage': 400000, 'annual_premium': 4000, 'risk_premium': 3200,
            'savings_premium': 400, 'pv_mortality': 800, 'pv_disability': 400,
            'expected_claims_year1': 120,
        },
        {
            'age': 45, 'accepted': 5, 'term_years': 100,
            'coverage': 500000, 'annual_premium': 5000, 'risk_premium': 4000,
            'savings_premium': 500, 'pv_mortality': 1000, 'pv_disability': 500,
            'expected_claims_year1': 150,
        },
    ]
    return {
        'simulation_id': 'SIM-PHINSAFE',
        'tables_version': 'test',
        'parameters': {'age_max': 55, 'age_min': 3},
        'portfolio_summary': {
            'accepted_customers': 10,
            'total_coverage': 1000000,
            'total_annual_premium': 10000,
            'total_risk_premium': 8000,
            'total_savings_premium': 1000,
        },
        'pricing_kernel': {'savings_rate': 0.125, 'savings_formula': 'risk_premium_markup'},
        'age_adl_matrix': {
            'distribution': {
                'histogram': [
                    {'age': age, 'accepted': row['accepted'], 'applied': row['accepted'], 'rejected': 0}
                    for row in rows
                    for age in (row['age'],)
                ],
            },
        },
        'accepted_money_by_age': rows,
        'accepted_money_integrity': {'all_checks_pass': True},
    }


def _parent():
    return {'id': 'CUST-PARENT', 'dob': '1998-04-02'}


def _policies():
    return [
        {
            'id': 'POL-A', 'customer_id': 'CUST-PARENT', 'status': 'active',
            'coverage_amount': 250000, 'annual_premium': 1200, 'savings_premium': 300,
            'billing': {},
        },
        {
            'id': 'POL-B', 'customer_id': 'CUST-PARENT', 'status': 'active',
            'coverage_amount': 100000, 'annual_premium': 600, 'savings_premium': 0,
            'billing': {},
        },
    ]


def test_market_share_takes_one_fifth_of_parents_under_the_cap():
    book = project_book(_snapshot(), parent_max_age=40, market_share_pct=10)
    assert book['integrity']['all_checks_pass'] is True
    assert book['parameters']['simulator_age_max'] == 55
    assert book['parameters']['parent_max_age'] == 40
    assert book['eligible_parents']['count'] == 4
    assert book['excluded']['below_parent_minimum']['accepted_parents'] == 1
    assert book['excluded']['above_parent_max_age']['accepted_parents'] == 5
    # 400,000 × 10% × 1/5 = 8,000. One age, so there is no cent gap.
    assert book['rider_book']['coverage'] == 8000.0
    assert book['rider_book']['annual_premium'] == 80.0
    assert book['rider_book']['risk_premium'] == 64.0
    assert book['rider_book']['savings_premium'] == 8.0
    assert book['pricing_identity']['benefit_gap_cents_versus_scaling_the_total'] == 0
    assert book['contract']['benefit_fraction'] == '1/5'
    assert book['contract']['waiting_years'] == 1
    assert book['contract']['settlement'] == 'permanent'


def test_full_share_is_exactly_one_fifth_of_the_eligible_face():
    book = project_book(_snapshot(), parent_max_age=40, market_share_pct=100)
    assert book['rider_book']['coverage'] == 80000.0
    assert book['rider_book']['coverage'] * BENEFIT_DENOMINATOR == 400000.0


def test_parent_max_age_must_be_below_the_simulator_max():
    with pytest.raises(PhinSafeIntegrityError, match='lower than the simulator'):
        project_book(_snapshot(), parent_max_age=55, market_share_pct=10)
    with pytest.raises(PhinSafeIntegrityError, match='lower than the simulator'):
        project_book(_snapshot(), parent_max_age=56, market_share_pct=10)


def test_same_cap_communities_rebuild_the_single_book():
    book = project_book(_snapshot(), parent_max_age=40, market_share_pct=100, communities=[
        {'community_id': 'north', 'label': 'North', 'max_joining_age': 40, 'member_weight_pct': 60},
        {'community_id': 'south', 'label': 'South', 'max_joining_age': 40, 'member_weight_pct': 40},
    ])
    north, south = book['communities']
    assert north['coverage'] == 48000.0
    assert south['coverage'] == 32000.0
    assert north['coverage'] + south['coverage'] == book['rider_book']['coverage']
    assert north['annual_premium'] + south['annual_premium'] == book['rider_book']['annual_premium']
    assert north['accepted_parents'] + south['accepted_parents'] == book['eligible_parents']['count']


def test_a_younger_community_does_not_receive_older_parents():
    book = project_book(_snapshot(), parent_max_age=50, market_share_pct=100, communities=[
        {'community_id': 'young', 'label': 'Young', 'max_joining_age': 32, 'member_weight_pct': 50},
        {'community_id': 'open', 'label': 'Open', 'max_joining_age': 50, 'member_weight_pct': 50},
    ])
    young = next(row for row in book['communities'] if row['community_id'] == 'young')
    opened = next(row for row in book['communities'] if row['community_id'] == 'open')
    # Age 30 face 400,000 × 1/5 × 50% = 40,000. Age 45 is outside the young cap.
    assert young['coverage'] == 40000.0
    # Age 30 half plus age 45 half: 40,000 + 50,000.
    assert opened['coverage'] == 90000.0
    assert young['coverage'] + opened['coverage'] < book['rider_book']['coverage']


def test_community_weights_must_sum_to_100():
    with pytest.raises(PhinSafeIntegrityError, match='sum to 100'):
        project_book(_snapshot(), parent_max_age=40, market_share_pct=10, communities=[
            {'community_id': 'only', 'max_joining_age': 40, 'member_weight_pct': 40},
        ])


def test_book_anchor_is_idempotent_and_covers_the_hash():
    book = project_book(_snapshot(), parent_max_age=40, market_share_pct=10)
    ledger = _Ledger()
    first = anchor_book(ledger, book, actor='actuary')
    second = anchor_book(ledger, book, actor='actuary')
    assert first['entry_id'] == second['entry_id']
    assert len(ledger.events) == 1
    assert ledger.events[0]['event_type'] == 'phinsafe_book_anchored'
    assert ledger.events[0]['payload']['document_hash'] == book['document_hash']
    tampered = dict(book)
    tampered['rider_book'] = dict(book['rider_book'])
    tampered['rider_book']['coverage'] = 1
    with pytest.raises(PhinSafeIntegrityError, match='does not verify'):
        anchor_book(ledger, tampered, actor='actuary')


def test_settlement_is_one_fifth_of_each_policy_and_waits_one_year():
    book = project_book(_snapshot(), parent_max_age=40, market_share_pct=10)
    with pytest.raises(PhinSafeIntegrityError, match='waiting period'):
        bind_rider(
            book=book, customer=_parent(), policies=_policies(),
            community_id='all-communities', join_date='2026-06-01',
            pregnancy_start='2026-12-01',
        )
    bound = bind_rider(
        book=book, customer=_parent(), policies=_policies(),
        community_id='all-communities', join_date='2026-06-01',
        pregnancy_start='2027-06-01',
    )
    rider = bound['rider']
    assert rider['parent_age_at_join'] == 28
    assert rider['coverage_starts'] == '2027-06-01'
    assert rider['status'] == 'in_force'
    assert rider['benefit'] == 70000.0
    assert rider['annual_premium'] == 360.0
    assert rider['savings_premium'] == 60.0
    slices = {row['policy_id']: row for row in rider['slices']}
    assert slices['POL-A']['benefit'] == 50000.0
    assert slices['POL-B']['benefit'] == 20000.0
    assert slices['POL-A']['benefit'] * 5 == slices['POL-A']['parent_coverage']
    assert slices['POL-B']['benefit'] * 5 == slices['POL-B']['parent_coverage']
    assert bound['bill']['id'].startswith('BILL-PS-')
    assert len(bound['bill']['id']) <= 50
    assert bound['bill']['type'] == 'phinsafe_rider'
    assert bound['policy_patches']['POL-A']['billing']['phinsafe']['separate_from_parent_premium'] is True

    ledger = _Ledger()
    anchor = anchor_rider(ledger, bound, actor='underwriter')
    assert anchor['event_type'] == 'phinsafe_rider_bound'
    assert ledger.events[0]['payload']['benefit'] == 70000.0
    again = anchor_rider(ledger, bound, actor='underwriter')
    assert again['entry_id'] == anchor['entry_id']
    assert len(ledger.events) == 1


def test_claim_stays_inside_the_settled_benefit_after_the_wait():
    book = project_book(_snapshot(), parent_max_age=40, market_share_pct=10)
    bound = bind_rider(
        book=book, customer=_parent(), policies=_policies(),
        community_id='all-communities', join_date='2026-06-01',
    )
    rider = bound['rider']
    assert rider['status'] == 'waiting'
    with pytest.raises(PhinSafeIntegrityError, match='waiting period'):
        open_claim(
            rider, amount=1000, incident_date='2026-08-01', pregnancy_start='2026-08-01',
        )
    opened = open_claim(
        rider, amount=1000, incident_date='2028-01-15', pregnancy_start='2027-07-01',
    )
    assert opened['claim']['status'] == 'pending'
    assert opened['claim']['id'].startswith('CLM-PS-')
    assert len(opened['claim']['id']) <= 50
    rider['open_claims_cents'] = opened['open_claims_cents']
    rider['first_pregnancy_start'] = opened['first_pregnancy_start']
    with pytest.raises(PhinSafeIntegrityError, match='remaining'):
        open_claim(
            rider, amount=70000, incident_date='2028-02-01', pregnancy_start='2027-07-01',
        )
    with pytest.raises(PhinSafeIntegrityError, match='already settled'):
        open_claim(
            rider, amount=10, incident_date='2028-02-01', pregnancy_start='2028-01-01',
        )


def test_generated_simulation_slice_keeps_its_identities():
    params = SimulationParams(
        customer_count=80,
        age_min=18,
        age_max=54,
        age_mean=34,
        age_std=8,
        policy_term_mode='fixed',
        policy_term_fixed=12,
        coverage_min=50000,
        coverage_max=200000,
        coverage_median=100000,
        savings_rate=0.5,
        savings_formula='risk_premium_markup',
    )
    simulation = get_portfolio_simulator().generate_portfolio(params)
    assert simulation['accepted_money_integrity']['all_checks_pass'] is True
    assert simulation['integration_ready']['phinsafe'] is True
    book = project_book(
        simulation,
        parent_max_age=36,
        market_share_pct=12.5,
        communities=[
            {'community_id': 'city', 'label': 'City', 'max_joining_age': 30, 'member_weight_pct': 25},
            {'community_id': 'town', 'label': 'Town', 'max_joining_age': 36, 'member_weight_pct': 75},
        ],
    )
    assert book['integrity']['all_checks_pass'] is True
    assert book['parameters']['parent_max_age'] < simulation['parameters']['age_max']
    covered = sum(row['coverage'] for row in book['communities'])
    assert covered <= book['rider_book']['coverage'] + 0.001
    assert book['rider_book']['components_sum_to_premium'] is True


def test_billing_cycle_adds_a_separate_phinsafe_installment():
    orchestrator = ProcessPipelineOrchestrator(policies={
        'POL-A': {
            'id': 'POL-A',
            'customer_id': 'CUST-PARENT',
            'status': 'active',
            'annual_premium': 1200,
            'monthly_premium': 100,
            'health_wallet': {'allocation_percentage': 25},
            'riders': {
                'phinsafe': {
                    'rider_id': 'PHINSAFE-TEST',
                    'customer_id': 'CUST-PARENT',
                    'primary_policy_id': 'POL-A',
                    'policy_ids': ['POL-A'],
                    'join_date': '2026-06-01',
                    'annual_premium_cents': 36000,
                    'savings_premium_cents': 6000,
                },
            },
        },
    })
    result = orchestrator.automate_billing_cycle('POL-A')
    assert result['success'] is True
    assert result['bill']['amount_due'] == 100
    assert result['phinsafe_bill']['type'] == 'phinsafe_rider'
    assert result['phinsafe_bill']['amount'] == 30.0
    assert result['phinsafe_bill_id'] in orchestrator.billing


def _post(url, payload, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read().decode('utf-8')), resp.status
    except HTTPError as exc:
        return json.loads(exc.read().decode('utf-8')), exc.code


def test_actuary_dashboard_api_anchors_then_binds():
    import web_portal.server as portal

    class _Server(HTTPServer):
        allow_reuse_address = True

    server = _Server(('127.0.0.1', 0), portal.PortalHandler)
    port = server.server_address[1]
    import threading
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f'http://127.0.0.1:{port}'
        login, status = _post(base + '/api/login', {'username': 'admin', 'password': 'admin123'})
        assert status == 200
        token = login['token']
        denied, status = _post(base + '/api/actuarial/phinsafe/project', {
            'simulation_id': 'missing', 'parent_max_age': 40, 'market_share_pct': 10,
        })
        assert status == 403
        assert 'error' in denied

        simulated, status = _post(base + '/api/actuarial/simulate', {
            'customer_count': 40,
            'age_min': 20,
            'age_max': 50,
            'age_mean': 32,
            'age_std': 6,
            'policy_term_mode': 'fixed',
            'policy_term_fixed': 10,
            'savings_rate': 0.25,
            'savings_formula': 'risk_premium_markup',
        }, token)
        assert status == 200
        simulation_id = simulated['simulation']['simulation_id']
        assert simulated['simulation']['accepted_money_integrity']['all_checks_pass'] is True

        book_body, status = _post(base + '/api/actuarial/phinsafe/project', {
            'simulation_id': simulation_id,
            'parent_max_age': 34,
            'market_share_pct': 20,
            'communities': [
                {'community_id': 'open-community', 'label': 'Open', 'max_joining_age': 34, 'member_weight_pct': 100},
            ],
        }, token)
        assert status == 200, book_body
        book = book_body['book']
        assert book['integrity']['all_checks_pass'] is True
        assert book['ledger']['event_type'] == 'phinsafe_book_anchored'
        assert book['parameters']['parent_max_age'] < book['parameters']['simulator_age_max']

        portal.CUSTOMERS['CUST-SAFE'] = {
            'id': 'CUST-SAFE',
            'dob': '1996-03-01',
            'name': 'Parent To Be',
        }
        portal.POLICIES['POL-SAFE-1'] = {
            'id': 'POL-SAFE-1', 'customer_id': 'CUST-SAFE', 'status': 'active',
            'type': 'life', 'coverage_amount': 250000, 'annual_premium': 1200,
            'savings_premium': 240, 'billing': {},
        }
        portal.POLICIES['POL-SAFE-2'] = {
            'id': 'POL-SAFE-2', 'customer_id': 'CUST-SAFE', 'status': 'active',
            'type': 'life', 'coverage_amount': 100000, 'annual_premium': 480,
            'billing': {},
        }
        early, status = _post(base + '/api/actuarial/phinsafe/bind', {
            'simulation_id': simulation_id,
            'customer_id': 'CUST-SAFE',
            'policy_ids': ['POL-SAFE-1', 'POL-SAFE-2'],
            'community_id': 'open-community',
            'join_date': '2026-04-01',
            'pregnancy_start': '2026-06-01',
        }, token)
        assert status == 400
        assert 'waiting' in early['error']

        settled, status = _post(base + '/api/actuarial/phinsafe/bind', {
            'simulation_id': simulation_id,
            'customer_id': 'CUST-SAFE',
            'policy_ids': ['POL-SAFE-1', 'POL-SAFE-2'],
            'community_id': 'open-community',
            'join_date': '2026-04-01',
            'pregnancy_start': '2027-04-01',
        }, token)
        assert status == 200, settled
        assert settled['rider']['benefit'] == 70000.0
        assert settled['rider']['annual_premium'] == 336.0
        assert settled['ledger']['entry_hash']
        stored = portal.POLICIES['POL-SAFE-1']['riders']['phinsafe']
        assert stored['benefit'] == 50000.0
        assert stored['ledger_entry_id'] == settled['ledger']['entry_id']
        assert settled['bill']['id'] in portal.BILLING
        assert portal.POLICIES['POL-SAFE-1']['annual_premium'] == 1200

        claim, status = _post(base + '/api/actuarial/phinsafe/claim', {
            'policy_id': 'POL-SAFE-1',
            'amount': 2500,
            'incident_date': '2028-05-01',
            'pregnancy_start': '2027-04-01',
        }, token)
        assert status == 200, claim
        assert claim['claim']['status'] == 'pending'
        assert claim['claim']['id'] in portal.CLAIMS
        assert portal.POLICIES['POL-SAFE-1']['riders']['phinsafe']['open_claims_cents'] == 250000
    finally:
        server.shutdown()
        server.server_close()
