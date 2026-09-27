"""The portfolio simulation download must restate the same run.

The report model does not reprice anything. It checks that the sections the
PDF prints — portfolio, premium, demographics, declines, histogram, reinsurance,
and savings — still describe one book of lives.
"""

import json
import os
import random
import subprocess
import tempfile
import textwrap

from services.actuarial_service import (
    ActuarialTablesStore,
    PortfolioSimulator,
    SimulationParams,
)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_JS = os.path.join(ROOT, 'web_portal', 'static', 'simulation-report.js')
DASHBOARD = os.path.join(ROOT, 'web_portal', 'static', 'actuary-dashboard.html')


def _portfolio():
    random.seed(27)
    return PortfolioSimulator(ActuarialTablesStore()).generate_portfolio(SimulationParams(
        customer_count=400,
        age_min=30,
        age_max=80,
        age_mean=55,
        age_std=10,
        age_distribution='normal',
        coverage_min=50000,
        coverage_max=200000,
        coverage_median=100000,
    ))


def _run_model(sim):
    script = textwrap.dedent('''
        const fs = require('fs');
        const vm = require('vm');
        const sim = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
        const context = {};
        context.globalThis = context;
        vm.createContext(context);
        vm.runInContext(fs.readFileSync(process.argv[3], 'utf8'), context);
        const fmt = {
          money: (n) => Number(n || 0).toFixed(2),
          count: (n) => String(Math.round(Number(n || 0))),
          pct: (n) => Number(n || 0).toFixed(2),
          num: (n) => String(n),
        };
        const model = context.simulationReportModel(sim, fmt);
        process.stdout.write(JSON.stringify({
          allPass: model.allPass,
          failed: model.checks.filter((item) => !item.ok).map((item) => item.name),
          accepted: model.headline.accepted,
          gross: model.headline.grossPremium,
          applied: model.headline.applied,
          tables: model.tables.map((table) => table.title),
        }));
    ''')
    with tempfile.TemporaryDirectory() as folder:
        runner = os.path.join(folder, 'run.js')
        blob = os.path.join(folder, 'sim.json')
        with open(runner, 'w', encoding='utf-8') as handle:
            handle.write(script)
        with open(blob, 'w', encoding='utf-8') as handle:
            json.dump(sim, handle)
        completed = subprocess.run(
            ['node', runner, blob, REPORT_JS],
            text=True,
            capture_output=True,
            check=False,
        )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)
    return json.loads(completed.stdout)


def test_dashboard_pdf_is_the_full_simulation():
    html = open(DASHBOARD, encoding='utf-8').read()
    assert '<script src="/simulation-report.js"></script>' in html
    assert 'phins_portfolio_simulation_' in html
    assert 'Portfolio Simulation Report' in html
    assert 'Data integrity:' in html
    assert "downloadAgeAdlReport('pdf')" in html


def test_report_model_reconciles_a_real_simulation():
    sim = _portfolio()
    model = _run_model(sim)
    assert model['failed'] == [], model['failed']
    assert model['allPass'] is True
    assert model['accepted'] == str(sim['portfolio_summary']['accepted_customers'])
    assert model['applied'] == str(sim['portfolio_summary']['requested_customers'])
    assert model['gross'] == f"{sim['profitability']['gross_premium']:.2f}"
    for title in (
        'Portfolio summary',
        'Premium reconciliation',
        'Profitability',
        'Risk',
        'Declined applications',
        'Age distribution by year',
        'Reinsurance indication',
        'Savings allocation',
    ):
        assert title in model['tables']


def test_report_model_fails_when_an_accepted_count_is_changed():
    sim = _portfolio()
    sim['portfolio_summary']['accepted_customers'] += 1
    model = _run_model(sim)
    assert model['allPass'] is False
    assert any('accepted' in name for name in model['failed'])
