"""PhinSafe downloads and annual revenue-center outlines restate published books.

The report does not reprice. Platform centers stay at outline and forecast
method: a missing ledger is not printed as zero.
"""

import copy
import json
import os
import subprocess
import tempfile
import textwrap

from services.phinsafe_rider import develop_portfolio, project_book


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_JS = os.path.join(ROOT, 'web_portal', 'static', 'phinsafe-report.js')
CENTERS_JS = os.path.join(ROOT, 'web_portal', 'static', 'revenue-centers.js')
DASHBOARD = os.path.join(ROOT, 'web_portal', 'static', 'actuary-dashboard.html')


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
                    {'age': row['age'], 'accepted': row['accepted'], 'applied': row['accepted'], 'rejected': 0}
                    for row in rows
                ],
            },
        },
        'accepted_money_by_age': rows,
        'accepted_money_integrity': {'all_checks_pass': True},
    }


def _book():
    return project_book(_snapshot(), parent_max_age=40, market_share_pct=10)


def _node(script, payload, scripts):
    runner_source = textwrap.dedent(script)
    with tempfile.TemporaryDirectory() as folder:
        runner = os.path.join(folder, 'run.js')
        blob = os.path.join(folder, 'payload.json')
        with open(runner, 'w', encoding='utf-8') as handle:
            handle.write(runner_source)
        with open(blob, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle)
        completed = subprocess.run(
            ['node', runner, blob, *scripts],
            text=True,
            capture_output=True,
            check=False,
        )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)
    return json.loads(completed.stdout)


def _report(book, portfolio=None):
    return _node(
        '''
        const fs = require('fs');
        const vm = require('vm');
        const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
        const context = {};
        context.globalThis = context;
        vm.createContext(context);
        vm.runInContext(fs.readFileSync(process.argv[3], 'utf8'), context);
        const fmt = {
          money: (n) => Number(n).toFixed(2),
          count: (n) => String(Math.round(Number(n))),
          pct: (n) => Number(n).toFixed(2),
          num: (n) => String(n),
        };
        const model = context.phinsafeReportModel(payload.book, payload.portfolio, fmt);
        const csv = context.phinsafeReportCsv(model);
        process.stdout.write(JSON.stringify({
          allPass: model.allPass,
          failed: model.checks.filter((item) => !item.ok).map((item) => item.name),
          simulationId: model.headline.simulationId,
          tables: model.tables.map((table) => table.title),
          csvHasSimulation: csv.indexOf(model.headline.simulationId) >= 0,
          csvPass: csv.indexOf('PASS') >= 0,
          portfolio: model.headline.portfolio,
        }));
        ''',
        {'book': book, 'portfolio': portfolio},
        [REPORT_JS],
    )


def _centers(unified, book=None, portfolio=None, platforms=None):
    return _node(
        '''
        const fs = require('fs');
        const vm = require('vm');
        const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
        const context = {};
        context.globalThis = context;
        vm.createContext(context);
        vm.runInContext(fs.readFileSync(process.argv[3], 'utf8'), context);
        const block = context.buildRevenueCenters(payload);
        process.stdout.write(JSON.stringify({
          method: block.method,
          checks: block.checks,
          centers: block.centers.map((center) => ({
            id: center.id,
            reporting: center.reporting,
            financial_reporting: center.financial_reporting,
            financial_statement: center.financial_statement,
            figures: center.figures,
            forecast_length: (center.forecast || []).length,
            forecast0: (center.forecast || [])[0] || null,
            figure_labels: (center.figure_rows || []).map((row) => row.label),
          })),
        }));
        ''',
        {
            'unified': unified,
            'phinsafe': book,
            'phinsafePortfolio': portfolio,
            'platforms': platforms,
        },
        [CENTERS_JS],
    )


def test_dashboard_wires_phinsafe_downloads_and_revenue_centers():
    html = open(DASHBOARD, encoding='utf-8').read()
    assert '<script src="/phinsafe-report.js"></script>' in html
    assert '<script src="/revenue-centers.js"></script>' in html
    assert "downloadPhinsafeReport('pdf')" in html
    assert "downloadPhinsafeReport('csv')" in html
    assert 'Download PDF report' in html
    assert 'Download CSV data' in html
    assert 'id="annual-src-phinsafe"' in html
    assert 'PhinSafe rider' in html
    assert 'B.7 Revenue centers' in html
    assert 'annualRevenueCentersHtml' in html
    assert 'buildRevenueCenters' in html
    assert 'Revenue Centers (B.7)' in html
    assert 'Pipeline: ${bound}/4 simulation sources bound' in html
    assert 'publishPhinsafeBook' in html
    assert 'Run the PhinSafe test first.' in html


def test_report_model_passes_a_real_book_and_prints_its_simulation():
    book = _book()
    model = _report(book)
    assert model['failed'] == [], model['failed']
    assert model['allPass'] is True
    assert model['simulationId'] == 'SIM-PHINSAFE'
    assert model['csvHasSimulation'] is True
    assert model['csvPass'] is True
    assert model['portfolio'] == 'not developed'
    for title in ('Contract', 'Rider book', 'Communities', 'Offspring portfolio'):
        assert title in model['tables']
    rider = book['rider_book']
    communities = book['communities']
    assert sum(row['coverage_cents'] for row in communities) == rider['coverage_cents']
    assert sum(row['annual_premium_cents'] for row in communities) == rider['annual_premium_cents']
    assert sum(row['savings_premium_cents'] for row in communities) == rider['savings_premium_cents']
    assert sum(row['accepted_parents'] for row in communities) == rider['accepted_parents']


def test_report_model_passes_a_younger_community_cap():
    book = project_book(_snapshot(), parent_max_age=50, market_share_pct=100, communities=[
        {'community_id': 'young', 'label': 'Young', 'max_joining_age': 32, 'member_weight_pct': 50},
        {'community_id': 'open', 'label': 'Open', 'max_joining_age': 50, 'member_weight_pct': 50},
    ])
    model = _report(book)
    assert model['allPass'] is True, model['failed']
    assert sum(row['coverage_cents'] for row in book['communities']) < book['rider_book']['coverage_cents']


def test_report_model_fails_when_a_community_weight_is_changed():
    book = copy.deepcopy(_book())
    book['communities'][0]['member_weight_pct'] = 90
    model = _report(book)
    assert model['allPass'] is False
    assert any('weight' in name for name in model['failed'])


def test_report_model_fails_when_community_cents_move():
    book = copy.deepcopy(_book())
    book['communities'][0]['coverage_cents'] += 1
    model = _report(book)
    assert model['allPass'] is False
    assert any('reconcile' in name for name in model['failed'])


def test_report_model_includes_a_real_offspring_portfolio():
    book = _book()
    portfolio = develop_portfolio(book, benefit_termination_age=18)
    model = _report(book, portfolio)
    assert model['allPass'] is True, model['failed']
    assert model['portfolio'] == 'developed'
    assert 'Offspring schedule' in model['tables']
    tampered = copy.deepcopy(portfolio)
    tampered['schedule'][0]['premium_cents'] += 1
    failed = _report(book, tampered)
    assert failed['allPass'] is False


def test_revenue_centers_keep_platform_amounts_unpublished():
    block = _centers(None)
    by_id = {center['id']: center for center in block['centers']}
    assert by_id['phins_unified']['reporting'] == 'not_bound'
    assert by_id['phins_unified']['figures'] is None
    assert by_id['phinsafe']['reporting'] == 'not_bound'
    assert by_id['phinsafe']['figures'] is None
    for center_id in ('health_wallet_supplier_margin', 'investments_markup', 'technology_sales'):
        center = by_id[center_id]
        assert center['reporting'] == 'outline_only'
        assert center['financial_reporting'] == 'not_bound'
        assert center['financial_statement'] is False
        assert center['figures'] is None
        assert center['forecast_length'] == 0
    assert all(center['financial_statement'] is False for center in block['centers'])
    assert all(item['ok'] for item in block['checks'])
    withheld = _centers(
        {'simulation_id': 'SIM-OTHER', 'accepted': 10, 'coverage': 1, 'annual_premium': 2},
        _book(),
    )
    safe = next(center for center in withheld['centers'] if center['id'] == 'phinsafe')
    assert safe['reporting'] == 'withheld'
    assert safe['figures'] is None
    assert safe['forecast_length'] == 0


def test_revenue_centers_copy_the_bound_snapshots_and_drop_injected_amounts():
    book = _book()
    portfolio = develop_portfolio(book, benefit_termination_age=4)
    unified = {
        'simulation_id': 'SIM-PHINSAFE',
        'accepted': 10,
        'coverage': 1000000,
        'annual_premium': 10000,
        'annual_expected_claims': None,
        'year1_loss_ratio': None,
    }
    block = _centers(unified, book, portfolio, platforms=[{
        'id': 'partner_desk',
        'name': 'Partner desk',
        'figures': {'annual_premium': 999},
        'forecast': [{'year': 1, 'premium': 999}],
    }])
    by_id = {center['id']: center for center in block['centers']}
    unified_center = by_id['phins_unified']
    assert unified_center['reporting'] == 'bound'
    assert unified_center['figures']['simulation_id'] == 'SIM-PHINSAFE'
    assert unified_center['figures']['annual_premium'] == 10000
    assert unified_center['figures']['annual_expected_claims'] is None
    assert unified_center['figures']['year1_loss_ratio'] is None
    assert unified_center['figures']['product_id'] == 'phins_pure_risk_adjustable'
    assert 'Year-1 loss ratio' not in unified_center['figure_labels']
    safe = by_id['phinsafe']
    assert safe['reporting'] == 'bound'
    assert safe['figures']['document_hash'] == book['document_hash']
    assert safe['figures']['coverage'] == book['rider_book']['coverage']
    assert safe['forecast_length'] == 4
    assert safe['forecast0']['premium'] == portfolio['schedule'][0]['premium']
    assert safe['forecast0']['expected_claims'] == portfolio['schedule'][0]['expected_claims']
    assert safe['forecast0']['savings'] == portfolio['schedule'][0]['savings']
    partner = by_id['partner_desk']
    assert partner['figures'] is None
    assert partner['forecast_length'] == 0
    assert partner['financial_statement'] is False
    assert all(item['ok'] for item in block['checks'])
    tampered = copy.deepcopy(portfolio)
    tampered['schedule'][0]['premium_cents'] += 1
    drifted = _centers(unified, book, tampered)
    drifted_safe = next(center for center in drifted['centers'] if center['id'] == 'phinsafe')
    forecast_check = next(item for item in drifted['checks'] if item['name'].startswith('PhinSafe forecast'))
    assert drifted_safe['forecast_length'] == 0
    assert forecast_check['ok'] is False
