/**
 * Full portfolio-simulation report.
 *
 * The download prints the snapshot the simulator already published.
 * It does not reprice the book. `simulationReportModel` only checks that
 * the published sections still describe the same lives and the same premium.
 */
(function (root) {
  function num(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : 0;
  }

  function sumValues(obj) {
    return Object.values(obj || {}).reduce((acc, value) => acc + num(value), 0);
  }

  function near(left, right, tolerance) {
    return Math.abs(num(left) - num(right)) <= tolerance;
  }

  function pairCount(obj, count) {
    return Object.entries(obj || {}).map(([key, value]) => [String(key), count(value)]);
  }

  function simulationReportModel(sim, fmt) {
    const money = fmt.money;
    const count = fmt.count;
    const pct = fmt.pct;
    const summary = sim.portfolio_summary || {};
    const prof = sim.profitability || {};
    const risk = sim.risk_metrics || {};
    const demo = sim.demographics || {};
    const declined = sim.declined || {};
    const matrix = sim.age_adl_matrix || {};
    const totals = matrix.totals || {};
    const recon = sim.premium_reconciliation || {};
    const identities = recon.identities || {};
    const kernel = sim.pricing_kernel || {};
    const params = sim.parameters || {};
    const dist = matrix.distribution || {};
    const hist = dist.histogram || [];
    const cap = matrix.max_acceptance_age != null ? Number(matrix.max_acceptance_age) : 65;
    const reins = sim.reinsurance_program || {};
    const savings = sim.savings_allocation || {};
    const auto = sim.automation || {};
    const checks = [];

    function check(name, ok) {
      checks.push({ name: name, ok: !!ok });
    }

    check('premium reconciliation identities', !!recon.all_identities_pass);
    Object.entries(identities).forEach(([name, identity]) => {
      if (identity && typeof identity.check === 'boolean') {
        check('premium: ' + name.replace(/_/g, ' '), identity.check);
      }
    });
    check('age ledger identities', !!(matrix.integrity && matrix.integrity.all_checks_pass));
    Object.entries((matrix.integrity || {}).checks || {}).forEach(([name, ok]) => {
      check('ledger: ' + name.replace(/_/g, ' '), ok);
    });
    check('accepted matches portfolio summary', num(totals.accepted) === num(summary.accepted_customers));
    check('rejected matches declined count', num(totals.rejected) === num(declined.count));
    check('applied matches requested customers', num(totals.applied) === num(summary.requested_customers));
    check('premium components sum to gross premium', near(
      num(prof.risk_premium) + num(prof.savings_premium) + num(prof.expense_loading) + num(prof.profit_margin),
      prof.gross_premium,
      1
    ));
    check('portfolio annual premium matches gross premium', near(summary.total_annual_premium, prof.gross_premium, 1));
    check('portfolio risk premium matches profitability', near(summary.total_risk_premium, prof.risk_premium, 1));
    check('portfolio savings premium matches profitability', near(summary.total_savings_premium, prof.savings_premium, 1));
    check('age bands sum to accepted lives', sumValues(demo.age_distribution) === num(summary.accepted_customers));
    check('gender sums to accepted lives', num(demo.gender && demo.gender.male) + num(demo.gender && demo.gender.female) === num(summary.accepted_customers));
    check('smoking sums to accepted lives', sumValues(demo.smoking) === num(summary.accepted_customers));
    check('ethnicity sums to accepted lives', sumValues(demo.ethnicity) === num(summary.accepted_customers));
    check('ADL distribution sums to accepted lives', sumValues(demo.adl_distribution) === num(summary.accepted_customers));
    check('coverage bands sum to accepted lives', sumValues(demo.coverage_distribution) === num(summary.accepted_customers));
    check('term bands sum to accepted lives', sumValues(demo.term_distribution) === num(summary.accepted_customers));
    check('decline reasons sum to declined count', sumValues(declined.reasons) === num(declined.count));

    const histApplied = hist.reduce((acc, row) => acc + num(row.applied), 0);
    const histAccepted = hist.reduce((acc, row) => acc + num(row.accepted), 0);
    const histRejected = hist.reduce((acc, row) => acc + num(row.rejected), 0);
    check('histogram applied matches requested customers', histApplied === num(summary.requested_customers));
    check('histogram accepted matches portfolio', histAccepted === num(summary.accepted_customers));
    check('histogram rejected matches declined count', histRejected === num(declined.count));
    check('histogram applied equals accepted plus rejected', hist.every((row) => num(row.applied) === num(row.accepted) + num(row.rejected)));
    check('no accepted life older than the acceptance cap', hist.every((row) => num(row.age) <= cap || num(row.accepted) === 0));
    check('reserve indication is 1.5 times PV claims', near(risk.reserve_requirement, num(risk.total_expected_claims) * 1.5, 1));

    const requested = num(summary.requested_customers);
    const expectedRate = requested ? (num(summary.accepted_customers) / requested) * 100 : 0;
    check('acceptance rate matches accepted over requested', near(summary.acceptance_rate, expectedRate, 0.02));

    const reinsIntegrity = reins.data_integrity || {};
    if (Object.keys(reinsIntegrity).length) {
      check('reinsurance gross premium reconciles', !!reinsIntegrity.gross_premium_reconciles);
      check('ceded exposure stays within total coverage', !!reinsIntegrity.ceded_exposure_within_total);
      check('reinsurance contracts stay within the portfolio', !!reinsIntegrity.contracts_within_portfolio);
    }
    if (savings.data_integrity) {
      check('savings allocation reconciles to gross premium', !!savings.data_integrity.gross_premium_reconciles);
    }

    const autoPct = (process) => pct(num(process && process.total_automation_pct) * 100);
    const autoManual = (process, key) => pct(num(process && process[key]) * 100);

    const tables = [
      {
        title: 'Portfolio summary',
        columns: ['Metric', 'Value'],
        rows: [
          ['Requested customers', count(summary.requested_customers)],
          ['Accepted customers', count(summary.accepted_customers)],
          ['Declined customers', count(declined.count)],
          ['Acceptance rate', pct(summary.acceptance_rate)],
          ['Total coverage', money(summary.total_coverage)],
          ['Total annual premium', money(summary.total_annual_premium)],
          ['Total risk premium', money(summary.total_risk_premium)],
          ['Total savings premium', money(summary.total_savings_premium)],
          ['Average coverage', money(summary.avg_coverage)],
          ['Average premium', money(summary.avg_premium)],
          ['Average risk premium', money(summary.avg_risk_premium)],
          ['Average savings premium', money(summary.avg_savings_premium)],
        ],
      },
      {
        title: 'Premium reconciliation',
        note: 'Computed and expected come from the simulation snapshot.',
        columns: ['Identity', 'Computed', 'Expected', 'Delta', 'Check'],
        rows: [
          ['N x average premium', money((identities.n_times_avg_premium_equals_total || {}).computed), money((identities.n_times_avg_premium_equals_total || {}).expected), money((identities.n_times_avg_premium_equals_total || {}).delta), (identities.n_times_avg_premium_equals_total || {}).check ? 'PASS' : 'FAIL'],
          ['Components sum to total', money((identities.sum_of_components_equals_total || {}).computed), money((identities.sum_of_components_equals_total || {}).expected), money((identities.sum_of_components_equals_total || {}).delta), (identities.sum_of_components_equals_total || {}).check ? 'PASS' : 'FAIL'],
          ['Savings markup', (identities.savings_markup_identity || {}).applies ? money((identities.savings_markup_identity || {}).computed) : 'not applicable', (identities.savings_markup_identity || {}).applies ? money((identities.savings_markup_identity || {}).actual) : '—', (identities.savings_markup_identity || {}).applies ? money((identities.savings_markup_identity || {}).delta) : '—', (identities.savings_markup_identity || {}).check ? 'PASS' : 'FAIL'],
        ],
      },
      {
        title: 'Profitability',
        columns: ['Component', 'Amount'],
        rows: [
          ['Risk premium', money(prof.risk_premium)],
          ['Savings premium', money(prof.savings_premium)],
          ['Expense loading', money(prof.expense_loading)],
          ['Profit margin', money(prof.profit_margin)],
          ['Gross annual premium', money(prof.gross_premium)],
          ['Expected claims (annual)', money(prof.expected_claims)],
          ['Net profit', money(prof.net_profit)],
          ['Net margin', pct(prof.net_margin_pct)],
          ['Return on risk', pct(prof.return_on_risk)],
        ],
      },
      {
        title: 'Risk',
        columns: ['Metric', 'Value'],
        rows: [
          ['PV mortality claims', money(risk.pv_mortality_claims)],
          ['PV disability claims', money(risk.pv_disability_claims)],
          ['Total expected claims (PV)', money(risk.total_expected_claims)],
          ['Annual expected claims', money(risk.annual_expected_claims)],
          ['Year-1 expected claims', money(risk.expected_claims_year1)],
          ['Loss ratio, lifetime-annualised', pct(risk.loss_ratio)],
          ['Loss ratio basis', String(risk.loss_ratio_basis || '')],
          ['Loss ratio, year 1', pct(risk.loss_ratio_year1)],
          ['Reserve indication', money(risk.reserve_requirement)],
          ['Reserve basis', String(risk.reserve_requirement_basis || '')],
          ['Average term (years)', String(risk.avg_term_years != null ? risk.avg_term_years : '')],
          ['Mortality share of claims', pct(risk.mortality_pct_of_claims)],
          ['Disability share of claims', pct(risk.disability_pct_of_claims)],
        ],
      },
      {
        title: 'Simulation parameters',
        columns: ['Parameter', 'Value'],
        rows: [
          ['Customers requested', count(params.customer_count)],
          ['Age minimum', String(params.age_min != null ? params.age_min : '')],
          ['Age maximum (draw window)', String(params.age_max != null ? params.age_max : '')],
          ['Acceptance age cap', String(cap)],
          ['Age mean', String(params.age_mean != null ? params.age_mean : '')],
          ['Age standard deviation', String(params.age_std != null ? params.age_std : '')],
          ['Age distribution', String(params.age_distribution || '')],
          ['Coverage minimum', money(params.coverage_min)],
          ['Coverage maximum', money(params.coverage_max)],
          ['Coverage median', money(params.coverage_median)],
          ['Coverage distribution', String(params.coverage_distribution || '')],
          ['Term mode', String(params.policy_term_mode || '')],
          ['Term minimum', String(params.policy_term_min != null ? params.policy_term_min : '')],
          ['Term maximum', String(params.policy_term_max != null ? params.policy_term_max : '')],
          ['Male percent', pct(params.male_pct)],
          ['Female percent', pct(params.female_pct)],
          ['Smoker percent', pct(params.smoker_pct)],
          ['Former smoker percent', pct(params.former_smoker_pct)],
          ['Savings rate', String(params.savings_rate != null ? params.savings_rate : '')],
          ['Savings formula', String(params.savings_formula || '')],
          ['Product', String(params.product_id || kernel.product_id || '')],
        ],
      },
      {
        title: 'Accepted age bands',
        columns: ['Age band', 'Lives'],
        rows: pairCount(demo.age_distribution, count),
      },
      {
        title: 'Gender',
        columns: ['Gender', 'Lives'],
        rows: pairCount(demo.gender, count),
      },
      {
        title: 'Smoking',
        columns: ['Status', 'Lives'],
        rows: pairCount(demo.smoking, count),
      },
      {
        title: 'Ethnicity',
        columns: ['Ethnicity', 'Lives'],
        rows: pairCount(demo.ethnicity, count),
      },
      {
        title: 'ADL distribution (accepted)',
        columns: ['ADL', 'Lives'],
        rows: pairCount(demo.adl_distribution, count),
      },
      {
        title: 'Coverage distribution (accepted)',
        columns: ['Band', 'Lives'],
        rows: pairCount(demo.coverage_distribution, count),
      },
      {
        title: 'Term distribution (accepted)',
        columns: ['Term', 'Lives'],
        rows: pairCount(demo.term_distribution, count),
      },
      {
        title: 'Declined applications',
        note: 'Coverage declined ' + money(declined.coverage_total) + '. Reason counts sum to the declined total.',
        columns: ['Reason', 'Count'],
        rows: Object.keys(declined.reasons || {}).length
          ? pairCount(declined.reasons, count)
          : [['No declines', count(0)]],
      },
      {
        title: 'Age distribution by year',
        note: 'Every drawn age. Accepted lives stop at the acceptance cap. The maximum age is not a pile of the tail.',
        columns: ['Age', 'Applied', 'Accepted', 'Rejected'],
        rows: hist.map((row) => [String(row.age), count(row.applied), count(row.accepted), count(row.rejected)]).concat([
          ['Total', count(histApplied), count(histAccepted), count(histRejected)],
        ]),
      },
      {
        title: 'Automation',
        columns: ['Process', 'Automation', 'Manual'],
        rows: [
          ['Overall', autoPct({ total_automation_pct: auto.overall_automation_pct }), 'scale ' + String(auto.scale_factor != null ? auto.scale_factor : '')],
          ['Underwriting', autoPct(auto.underwriting), autoManual(auto.underwriting, 'manual_review')],
          ['Claims', autoPct(auto.claims), autoManual(auto.claims, 'manual_review')],
          ['Billing', autoPct(auto.billing), autoManual(auto.billing, 'manual_followup')],
        ],
      },
      {
        title: 'Pricing kernel',
        columns: ['Field', 'Value'],
        rows: [
          ['Product', String(kernel.product_id || '')],
          ['Age curve', String(kernel.age_curve_id || '')],
          ['Savings formula', String(kernel.savings_formula || '')],
          ['Savings rate', String(kernel.savings_rate != null ? kernel.savings_rate : '')],
          ['Claim model', String(kernel.claim_model || '')],
          ['Tables version', String(kernel.tables_version || sim.tables_version || '')],
          ['Config version', String(kernel.config_version || '')],
          ['Expense loading', String(kernel.expense_loading_pct != null ? kernel.expense_loading_pct : '')],
          ['Profit margin', String(kernel.profit_margin_pct != null ? kernel.profit_margin_pct : '')],
          ['Discount rate', String(kernel.discount_rate != null ? kernel.discount_rate : '')],
          ['Disability share of life', String(kernel.disability_share_of_life != null ? kernel.disability_share_of_life : '')],
          ['Disability band age', String(kernel.disability_band_age != null ? kernel.disability_band_age : '')],
        ],
      },
      {
        title: 'Reinsurance indication',
        columns: ['Field', 'Value'],
        rows: [
          ['Accepted lives', count(reins.accepted_lives)],
          ['Selected contracts', count(reins.selected_contracts)],
          ['Hedge share', pct(reins.hedge_share_pct)],
          ['Risk band', String(reins.risk_band || '')],
          ['Ceded exposure', money(reins.ceded_exposure)],
          ['Ceded expected claims (annual)', money(reins.ceded_expected_claims_annual)],
          ['Technical annual premium', money(reins.technical_annual_premium)],
          ['Total contract cost', money(reins.total_contract_cost)],
          ['Reserve relief estimate', money(reins.reserve_relief_estimate)],
          ['Net profit after reinsurance', money(reins.net_profit_after_reinsurance)],
        ],
      },
      {
        title: 'Savings allocation',
        columns: ['Field', 'Value'],
        rows: [
          ['Allocation percent', pct(savings.savings_allocation_pct)],
          ['Savings premium pass-through', money((savings.savings_balance_sheet || {}).savings_premium_pass_through)],
          ['Total to savings fund', money((savings.savings_balance_sheet || {}).total_to_savings_fund)],
          ['Gross premium retained on insurance', money((savings.insurance_balance_sheet || {}).gross_premium_retained)],
          ['Profit retained on insurance', money((savings.insurance_balance_sheet || {}).profit_retained)],
        ],
      },
    ];

    return {
      allPass: checks.every((item) => item.ok),
      checks: checks,
      tables: tables,
      cap: cap,
      headline: {
        simulationId: String(sim.simulation_id || ''),
        runAt: String(sim.run_at || ''),
        tablesVersion: String(sim.tables_version || ''),
        duration: String(sim.duration_seconds != null ? sim.duration_seconds : ''),
        accepted: count(summary.accepted_customers),
        applied: count(totals.applied),
        rejected: count(totals.rejected),
        grossPremium: money(prof.gross_premium),
        totalCoverage: money(summary.total_coverage),
      },
    };
  }

  root.simulationReportModel = simulationReportModel;
})(typeof window !== 'undefined' ? window : globalThis);
