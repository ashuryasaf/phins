"""Portfolio simulator and sandbox rulebook stay on the rate tables.

Accepted lives respect the decline threshold, the acceptance age cap and
the ADL coverage limits. Automatic approval, including maximum ADL, only
auto-issues. Year-1 claims equal the kernel probabilities. The sandbox
module applies the same gates and draws claims from those probabilities.
"""

import json
import subprocess
from pathlib import Path

from services.actuarial_service import (
    PortfolioSimulator,
    SimulationParams,
    get_actuarial_store,
)


def _run(age_max=70, count=60, **kwargs):
    store = get_actuarial_store()
    saved = {
        'auto_approve_enabled': store.config.auto_approve_enabled,
        'auto_approve_max_adl': store.config.auto_approve_max_adl,
        'auto_approve_require_clean_history': store.config.auto_approve_require_clean_history,
    }
    store.config.auto_approve_enabled = kwargs.get('auto', saved['auto_approve_enabled'])
    store.config.auto_approve_max_adl = kwargs.get('max_adl', saved['auto_approve_max_adl'])
    if 'clean' in kwargs:
        store.config.auto_approve_require_clean_history = kwargs['clean']
    try:
        sim = PortfolioSimulator(store)
        return sim.generate_portfolio(SimulationParams(
            customer_count=count,
            age_min=25,
            age_max=age_max,
            age_distribution='uniform',
            age_mean=45,
            age_std=8,
            coverage_min=50000,
            coverage_max=800000,
            coverage_distribution='uniform',
            coverage_median=200000,
            policy_term_mode='fixed',
            policy_term_fixed=10,
        ))
    finally:
        store.config.auto_approve_enabled = saved['auto_approve_enabled']
        store.config.auto_approve_max_adl = saved['auto_approve_max_adl']
        store.config.auto_approve_require_clean_history = saved['auto_approve_require_clean_history']


def test_accepted_book_obeys_underwriting_and_kernel_claims():
    result = _run()
    rules = result['underwriting_rules']
    flags = result['rule_integrity']
    assert flags['all_checks_pass'] is True
    assert rules['decline_threshold'] >= 1
    assert rules['max_acceptance_age'] == 65
    lives = result['priced_lives']
    assert lives
    assert len(lives) <= 2000
    decline = rules['decline_threshold']
    for life in lives:
        assert life['adl'] < decline
        assert life['age'] <= rules['max_acceptance_age']
        assert life['year1_identity_holds'] is True
        components = (
            life['risk_premium'] + life['savings_premium']
            + life['expense_loading'] + life['profit_margin']
        )
        assert abs(components - life['annual_premium']) < 0.05
        if life['exclude_disability']:
            assert life['disability_eligible'] is False
            assert life['prob_disability_year1'] == 0.0
        limit = rules['coverage_limits'].get(str(life['adl']))
        if limit is not None:
            assert life['coverage'] <= float(limit) + 0.01
    summary = result['portfolio_summary']
    assert summary['accepted_customers'] == len(lives) or summary['accepted_customers'] > len(lives)
    assert summary['accepted_customers'] >= 1


def test_maximum_adl_blocks_automatic_issue_only():
    result = _run(auto=True, max_adl=3, clean=False, count=80)
    rules = result['underwriting_rules']
    assert rules['auto_approve_enabled'] is True
    assert result['rule_integrity']['auto_approved_respects_max_adl'] is True
    assert result['rule_integrity']['all_checks_pass'] is True
    autos = [life for life in result['priced_lives'] if life['issuance'] == 'auto']
    referred = [life for life in result['priced_lives'] if life['issuance'] == 'referred']
    assert autos or referred
    for life in autos:
        assert life['adl'] <= 3
        assert life['uw_status'] == 'approved'
    for life in referred:
        assert life['uw_status'] == 'pending'
        assert life['adl'] < rules['decline_threshold']
    assert result['issuance']['auto_approved'] == result['portfolio_summary']['auto_approved_customers']
    assert result['issuance']['referred'] == result['portfolio_summary']['referred_customers']


def test_sandbox_rulebook_matches_maximum_adl_and_kernel_draw():
    root = Path(__file__).resolve().parents[1]
    script = r"""
const snap = require('./web_portal/static/sandbox-portfolio-snapshot.js');
const rules = {
  decline_threshold: 9,
  disability_exclusion_threshold: 8,
  max_acceptance_age: 65,
  coverage_limits: { '8': 500000 },
  auto_approve_enabled: true,
  auto_approve_max_adl: 3,
  auto_approve_min_age: 18,
  auto_approve_max_age: 60,
  auto_approve_max_coverage: 500000,
  auto_approve_max_risk_score: 0.25,
  auto_approve_require_clean_history: true,
};
const clean = snap.issueFromRules({
  age: 40, adl: 2, coverage: 200000, risk_score: 0.01, smoking_status: 'nonsmoker',
}, rules);
if (clean.uw_status !== 'approved' || clean.issuance !== 'auto') process.exit(2);
const overAdl = snap.issueFromRules({
  age: 40, adl: 5, coverage: 200000, risk_score: 0.01, smoking_status: 'nonsmoker',
}, rules);
if (overAdl.uw_status !== 'pending' || overAdl.issuance !== 'referred') process.exit(3);
const declined = snap.issueFromRules({
  age: 40, adl: 9, coverage: 200000, risk_score: 0.01, smoking_status: 'nonsmoker',
}, rules);
if (declined.uw_status !== 'declined' || declined.reason !== 'adl') process.exit(4);
const tooOld = snap.issueFromRules({
  age: 70, adl: 2, coverage: 200000, risk_score: 0.01, smoking_status: 'nonsmoker',
}, rules);
if (tooOld.reason !== 'age') process.exit(5);
const life = {
  uw_status: 'approved', policy_status: 'active', has_claim: false,
  disability_eligible: true,
  prob_mortality_year1: 0.5, prob_disability_year1: 0.5,
  life_sum: 100000, disability_sum: 25000,
};
const death = snap.kernelClaimEvent(life, 0.01);
if (!death || death.type !== 'mortality' || death.amount !== 100000) process.exit(6);
const monthlyDeath = snap.annualToMonthlyProb(0.5);
const disable = snap.kernelClaimEvent(life, monthlyDeath + 0.001);
if (!disable || disable.type !== 'disability' || disable.amount !== 25000) process.exit(7);
const none = snap.kernelClaimEvent(life, 0.999);
if (none) process.exit(8);
const excluded = Object.assign({}, life, { disability_eligible: false });
const noDisable = snap.kernelClaimEvent(excluded, monthlyDeath + 0.001);
if (noDisable) process.exit(9);
if (!snap.premiumComponentsMatch({
  risk_premium: 100, savings_premium: 40, expense_loading: 15, profit_margin: 15.5, annual_premium: 170.5,
})) process.exit(10);
if (!snap.premiumComponentsMatch({
  risk_premium: 100, savings_premium: 40, expense_loading: 15, profit_margin: 15.5,
  annual_premium: 999, issue_annual_premium: 170.5,
})) process.exit(11);
const referred = {
  uw_status: 'pending', policy_status: 'active',
  coverage_amount: 100000, annual_premium: 1200, monthly_premium: 100,
  issue_annual_premium: 1200,
  prob_mortality_year1: 0.12, prob_disability_year1: 0,
  life_sum: 100000, disability_sum: 25000, disability_eligible: true,
};
if (!snap.isInForcePolicy(referred)) process.exit(12);
if (snap.isInForcePolicy({ uw_status: 'pending', policy_status: 'pending' })) process.exit(13);
if (snap.isInForcePolicy({ uw_status: 'declined', policy_status: 'declined' })) process.exit(14);
if (snap.isInForcePolicy({ uw_status: 'approved', policy_status: 'terminated' })) process.exit(15);
const book = snap.kernelBook([
  referred,
  { uw_status: 'declined', policy_status: 'declined', annual_premium: 999, coverage_amount: 1, prob_mortality_year1: 1, life_sum: 1 },
]);
if (book.active !== 1 || book.coverage !== 100000) process.exit(16);
if (Math.abs(book.death - 12000) > 1e-6 || book.disability !== 0) process.exit(17);
if (Math.abs(book.lossRatio - (12000 / 1200)) > 1e-9) process.exit(18);
const lives = [];
for (let i = 0; i < 1000; i++) lives.push(Object.assign({}, referred));
const plan = snap.planOpeningClaims(lives);
const incidence = 1000 * snap.annualToMonthlyProb(0.12);
if (Math.abs(plan.incidence - incidence) > 1e-6) process.exit(19);
if (Math.abs(plan.claims.length - Math.floor(incidence)) > 2) process.exit(20);
if (!plan.claims.length || plan.claims[0].type !== 'mortality' || plan.claims[0].amount !== 100000) process.exit(21);
const grown = snap.buildForecast({
  startCustomers: 1000, growthPct: 10, premiumPerCustomer: 100,
  lossRatioPct: 50, horizon: 3, mortalityShare: 0.6,
});
const forecast = snap.portfolioSnapshot({
  annualPremiumBooked: 1200, lossRatioPct: 50, mortalityShare: 0.6,
  growthPct: 10, startCustomers: 1000, originalActivePolicies: 1000,
  portfolioCustomers: 96913, premiumPerCustomer: 100, rows: grown.rows,
});
if (!forecast.checks.ok || forecast.month1Customers !== 1000) process.exit(22);
if (Math.abs(forecast.growthFactor - (forecast.endCustomers / 1000)) > 1e-12) process.exit(23);
const labels = snap.snapshotLines(forecast).map(l => l.label);
if (!labels.includes('Simulated accepted lives')) process.exit(24);
if (!labels.includes('Original active policies')) process.exit(25);
if (!labels.includes('Growth factor (final month / original active policies)')) process.exit(26);
const drifted = snap.portfolioSnapshot({
  annualPremiumBooked: 1200, lossRatioPct: 50, mortalityShare: 0.6,
  growthPct: 10, startCustomers: 1000, originalActivePolicies: 40,
  premiumPerCustomer: 100, rows: grown.rows,
});
if (drifted.checks.ok || drifted.checks.originalOpeningIdentity) process.exit(27);
if (!clean.failed_gates || clean.failed_gates.length !== 0) process.exit(28);
if (!clean.basis || clean.basis.indexOf('probability') === -1) process.exit(29);
const highRisk = snap.issueFromRules({
  age: 40, adl: 2, coverage: 200000, risk_score: 0.01,
  prob_mortality_year1: 0.25, prob_disability_year1: 0.15,
  smoking_status: 'nonsmoker',
}, rules);
if (highRisk.uw_status !== 'pending' || highRisk.issuance !== 'referred') process.exit(30);
if (!highRisk.failed_gates || highRisk.failed_gates.indexOf('max_risk_score') === -1) process.exit(31);
if (highRisk.uw_status === 'declined' || !highRisk.basis || highRisk.basis.indexOf('not declined') === -1) process.exit(32);
if (!tooOld.basis || tooOld.basis.indexOf('not a decline') === -1) process.exit(33);
const authLife = {
  uw_status: 'approved', policy_status: 'active', disability_eligible: true,
  prob_mortality_year1: 0.08, prob_disability_year1: 0.04,
  life_sum: 100000, disability_sum: 25000,
};
const authOk = snap.claimAuthorization({ type: 'mortality', amount: 100000 }, authLife);
if (!authOk.ok || authOk.reason !== 'kernel_year1_probability') process.exit(34);
if (Math.abs(authOk.risk_score - 0.12) > 1e-9) process.exit(35);
const unknown = snap.claimAuthorization(
  { type: 'mortality', amount: 100000 },
  { uw_status: 'approved', policy_status: 'active', life_sum: 100000, disability_sum: 25000 }
);
if (unknown.ok || unknown.reason !== 'risk_score_unknown') process.exit(36);
const outOfForce = snap.claimAuthorization(
  { type: 'mortality', amount: 100000 },
  { uw_status: 'declined', policy_status: 'declined', prob_mortality_year1: 0.1, life_sum: 100000 }
);
if (outOfForce.ok || outOfForce.reason !== 'not_in_force') process.exit(37);
const badAmt = snap.claimAuthorization({ type: 'mortality', amount: 1 }, authLife);
if (badAmt.ok || badAmt.reason !== 'amount') process.exit(38);
const noDis = snap.claimAuthorization(
  { type: 'disability', amount: 25000 },
  Object.assign({}, authLife, { disability_eligible: false })
);
if (noDis.ok || noDis.reason !== 'disability_excluded') process.exit(39);
console.log('ok');
"""
    proc = subprocess.run(
        ['node', '-e', script],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert 'ok' in proc.stdout
