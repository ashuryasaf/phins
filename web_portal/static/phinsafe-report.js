/**
 * PhinSafe published-book report.
 *
 * The download prints the book (and, when present, the offspring portfolio)
 * the PhinSafe test already published. It does not reprice the rider.
 * The cover says PASS only when the published sections still describe that
 * same book. A missing offspring portfolio is a note, not a failure: the
 * testing book can be downloaded on its own.
 */
(function (root) {
  function num(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : 0;
  }

  function centsOf(row, key) {
    if (!row) return null;
    const raw = row[key + '_cents'];
    if (raw == null || raw === '') return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }

  function countOf(row, key) {
    if (!row || row[key] == null || row[key] === '') return null;
    const n = Number(row[key]);
    return Number.isFinite(n) ? n : null;
  }

  function near(left, right, tolerance) {
    return Math.abs(num(left) - num(right)) <= tolerance;
  }

  function showMoney(money, value) {
    if (value == null || value === '') return '';
    const n = Number(value);
    return Number.isFinite(n) ? money(n) : '';
  }

  function communitiesReconcile(book) {
    const rider = book.rider_book || {};
    const communities = book.communities || [];
    const cap = Number((book.parameters || {}).parent_max_age);
    if (!communities.length || !Number.isFinite(cap)) return false;
    const sameCap = communities.every((row) => Number(row.max_joining_age) === cap);
    const parentCounts = communities.map((row) => countOf(row, 'accepted_parents'));
    const riderParents = countOf(rider, 'accepted_parents');
    if (parentCounts.some((value) => value == null) || riderParents == null) return false;
    const parentSum = parentCounts.reduce((sum, value) => sum + value, 0);
    const keys = ['coverage', 'annual_premium', 'savings_premium'];
    const sums = keys.map((key) => {
      let total = 0;
      for (let i = 0; i < communities.length; i += 1) {
        const cents = centsOf(communities[i], key);
        if (cents == null) return null;
        total += cents;
      }
      return total;
    });
    const riderCents = keys.map((key) => centsOf(rider, key));
    if (sums.some((value) => value == null) || riderCents.some((value) => value == null)) return false;
    if (sameCap) {
      if (parentSum !== riderParents) return false;
      return sums.every((value, index) => value === riderCents[index]);
    }
    if (parentSum > riderParents) return false;
    return sums.every((value, index) => value <= riderCents[index]);
  }

  function portfolioScheduleHolds(book, portfolio) {
    const schedule = portfolio.schedule || [];
    const totals = portfolio.totals || {};
    const rider = book.rider_book || {};
    if (!schedule.length) return false;
    const face = centsOf(rider, 'coverage');
    const centComplete = face != null && schedule.every((row) => (
      centsOf(row, 'premium') != null
      && centsOf(row, 'expected_claims') != null
      && centsOf(row, 'savings') != null
      && centsOf(row, 'risk_premium') != null
      && centsOf(row, 'benefit_in_force') != null
    )) && centsOf(totals, 'premium') != null
      && centsOf(totals, 'expected_claims') != null
      && centsOf(totals, 'savings_account') != null;
    if (centComplete) {
      let premium = 0;
      let claims = 0;
      let savings = 0;
      for (let i = 0; i < schedule.length; i += 1) {
        const row = schedule[i];
        const rowPremium = centsOf(row, 'premium');
        const rowRisk = centsOf(row, 'risk_premium');
        const rowSavings = centsOf(row, 'savings');
        if (rowRisk + rowSavings !== rowPremium) return false;
        if (centsOf(row, 'benefit_in_force') !== face) return false;
        premium += rowPremium;
        claims += centsOf(row, 'expected_claims');
        savings += rowSavings;
      }
      return centsOf(totals, 'premium') === premium
        && centsOf(totals, 'expected_claims') === claims
        && centsOf(totals, 'savings_account') === savings;
    }
    let premium = 0;
    let claims = 0;
    let savings = 0;
    for (let i = 0; i < schedule.length; i += 1) {
      const row = schedule[i];
      if (!near(num(row.risk_premium) + num(row.savings), row.premium, 0.02)) return false;
      if (!near(row.benefit_in_force, rider.coverage, 0.02)) return false;
      premium += num(row.premium);
      claims += num(row.expected_claims);
      savings += num(row.savings);
    }
    return near(premium, totals.premium, 0.05)
      && near(claims, totals.expected_claims, 0.05)
      && near(savings, totals.savings_account, 0.05);
  }

  function phinsafeReportModel(book, portfolio, fmt) {
    const money = (fmt && fmt.money) || String;
    const count = (fmt && fmt.count) || String;
    const pct = (fmt && fmt.pct) || String;
    const checks = [];
    const notes = [];

    function check(name, ok, detail) {
      const row = { name: name, ok: !!ok };
      if (detail) row.detail = detail;
      checks.push(row);
    }

    if (!book || typeof book !== 'object') {
      check('published PhinSafe book', false, 'Run the PhinSafe test first.');
      return {
        allPass: false,
        checks: checks,
        notes: notes,
        tables: [],
        headline: { simulationId: '', documentHash: '', productId: 'phinsafe' },
      };
    }

    const params = book.parameters || {};
    const rider = book.rider_book || {};
    const eligible = book.eligible_parents || {};
    const contract = book.contract || {};
    const integrity = book.integrity || {};
    const communities = book.communities || [];

    check('published book carries a document hash', !!book.document_hash);
    check('published integrity passed', !!integrity.all_checks_pass);
    Object.keys(integrity.checks || {}).forEach((name) => {
      check('book: ' + name.replace(/_/g, ' '), !!integrity.checks[name]);
    });

    const weight = communities.reduce((sum, row) => sum + num(row.member_weight_pct), 0);
    check('community weights sum to 100', communities.length > 0 && Math.abs(weight - 100) <= 0.02, weight.toFixed(2));
    check('communities reconcile to the rider book', communitiesReconcile(book));
    check('benefit fraction is 1/5', String(params.benefit_fraction || contract.benefit_fraction || '') === '1/5');
    check('settlement is permanent', String(params.settlement || contract.settlement || '') === 'permanent');
    check('waiting period is one year', Number(params.waiting_years != null ? params.waiting_years : contract.waiting_years) === 1);

    const tables = [
      {
        title: 'Contract',
        columns: ['Term', 'Value'],
        rows: [
          ['Product', String(book.product_id || 'phinsafe')],
          ['Simulation', String(book.simulation_id || '')],
          ['Document hash', String(book.document_hash || '')],
          ['Benefit fraction', String(params.benefit_fraction || contract.benefit_fraction || '')],
          ['Settlement', String(params.settlement || contract.settlement || '')],
          ['Waiting years', String(params.waiting_years != null ? params.waiting_years : '')],
          ['Parent maximum age', String(params.parent_max_age != null ? params.parent_max_age : '')],
          ['Simulator maximum age', String(params.simulator_age_max != null ? params.simulator_age_max : '')],
          ['Market share %', String(params.market_share_pct != null ? params.market_share_pct : '')],
          ['Tables version', String(book.tables_version || '')],
        ],
      },
      {
        title: 'Eligible parents',
        columns: ['Field', 'Value'],
        rows: [
          ['Parents', count(eligible.count)],
          ['Coverage', showMoney(money, eligible.coverage)],
          ['Annual premium', showMoney(money, eligible.annual_premium)],
          ['Risk premium', showMoney(money, eligible.risk_premium)],
          ['Savings premium', showMoney(money, eligible.savings_premium)],
          ['Rule', String(eligible.rule || '')],
        ],
      },
      {
        title: 'Rider book',
        note: 'Savings are a deposit, not revenue. Amounts are the published cents.',
        columns: ['Field', 'Value'],
        rows: [
          ['Accepted parents', count(rider.accepted_parents)],
          ['Settled benefit', showMoney(money, rider.coverage)],
          ['Annual premium', showMoney(money, rider.annual_premium)],
          ['Risk premium', showMoney(money, rider.risk_premium)],
          ['Savings premium', showMoney(money, rider.savings_premium)],
          ['Expense and profit', showMoney(money, rider.expense_and_profit)],
          ['Annual expected claims', showMoney(money, rider.annual_expected_claims)],
          ['Loss ratio %', rider.loss_ratio_pct != null ? pct(rider.loss_ratio_pct) : ''],
        ],
      },
      {
        title: 'Communities',
        note: 'When every community cap equals the parent maximum, community cents equal the rider book. A younger cap does not receive older parents, so its sum stays at or under the rider book.',
        columns: ['Community', 'ID', 'Max age', 'Weight %', 'Parents', 'Benefit', 'Premium', 'Savings'],
        rows: communities.map((row) => [
          String(row.label || ''),
          String(row.community_id || ''),
          String(row.max_joining_age != null ? row.max_joining_age : ''),
          String(row.member_weight_pct != null ? row.member_weight_pct : ''),
          count(row.accepted_parents),
          showMoney(money, row.coverage),
          showMoney(money, row.annual_premium),
          showMoney(money, row.savings_premium),
        ]),
      },
    ];

    const excluded = book.excluded || {};
    const below = excluded.below_parent_minimum || {};
    const above = excluded.above_parent_max_age || {};
    if (Object.keys(excluded).length) {
      tables.push({
        title: 'Excluded from the rider',
        columns: ['Slice', 'Parents', 'Coverage', 'Annual premium'],
        rows: [
          ['Below parent minimum', count(below.accepted_parents), showMoney(money, below.coverage), showMoney(money, below.annual_premium)],
          ['Above parent maximum', count(above.accepted_parents), showMoney(money, above.coverage), showMoney(money, above.annual_premium)],
        ],
      });
    }

    if (!portfolio) {
      notes.push('Offspring portfolio is not developed. This report is the published testing book.');
      check('offspring portfolio', true, 'not developed; this report is the published testing book');
      tables.push({
        title: 'Offspring portfolio',
        note: notes[0],
        columns: ['Field', 'Value'],
        rows: [['Status', 'not developed']],
      });
    } else {
      const pintegrity = portfolio.integrity || {};
      const pparams = portfolio.parameters || {};
      const summary = portfolio.portfolio || {};
      const totals = portfolio.totals || {};
      check('offspring portfolio integrity passed', !!pintegrity.all_checks_pass);
      Object.keys(pintegrity.checks || {}).forEach((name) => {
        check('portfolio: ' + name.replace(/_/g, ' '), !!pintegrity.checks[name]);
      });
      check('offspring portfolio cites this book', String(portfolio.source_book_hash || '') === String(book.document_hash || ''));
      check('offspring portfolio matches the simulation', String(portfolio.simulation_id || '') === String(book.simulation_id || ''));
      check('schedule holds the published totals and the settled face', portfolioScheduleHolds(book, portfolio));
      tables.push({
        title: 'Offspring portfolio',
        columns: ['Field', 'Value'],
        rows: [
          ['Source book hash', String(portfolio.source_book_hash || '')],
          ['Period years', String(pparams.period_years != null ? pparams.period_years : '')],
          ['Period rule', String(pparams.period_rule || '')],
          ['Offspring', count(summary.offspring_count)],
          ['Benefit in force', showMoney(money, summary.benefit_in_force)],
          ['Term premium', showMoney(money, totals.premium)],
          ['Term expected claims', showMoney(money, totals.expected_claims)],
          ['Savings account', showMoney(money, totals.savings_account)],
          ['Term underwriting', showMoney(money, totals.underwriting)],
        ],
      });
      tables.push({
        title: 'Offspring schedule',
        note: 'Level amounts copied from the published portfolio. Risk premium plus savings equals premium. Benefit in force stays the settled face.',
        columns: ['Year', 'Age', 'Benefit', 'Premium', 'Risk premium', 'Savings', 'Expected claims'],
        rows: (portfolio.schedule || []).map((row) => [
          String(row.policy_year != null ? row.policy_year : ''),
          String(row.offspring_age != null ? row.offspring_age : ''),
          showMoney(money, row.benefit_in_force),
          showMoney(money, row.premium),
          showMoney(money, row.risk_premium),
          showMoney(money, row.savings),
          showMoney(money, row.expected_claims),
        ]),
      });
    }

    return {
      allPass: checks.every((item) => item.ok),
      checks: checks,
      notes: notes,
      tables: tables,
      headline: {
        simulationId: String(book.simulation_id || ''),
        documentHash: String(book.document_hash || ''),
        productId: String(book.product_id || 'phinsafe'),
        parents: count(rider.accepted_parents),
        coverage: showMoney(money, rider.coverage),
        premium: showMoney(money, rider.annual_premium),
        portfolio: portfolio ? 'developed' : 'not developed',
      },
    };
  }

  function csvCell(value) {
    const text = value == null ? '' : String(value);
    return /[",\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
  }

  function phinsafeReportCsv(model) {
    const section = (title, columns, rows) => [
      '# ' + title,
      (columns || []).map(csvCell).join(','),
      ...(rows || []).map((row) => row.map(csvCell).join(',')),
    ].join('\n');
    const sections = [
      section('Cover', ['Field', 'Value'], [
        ['Product', 'PhinSafe'],
        ['Simulation ID', model.headline.simulationId],
        ['Document hash', model.headline.documentHash],
        ['Data integrity', model.allPass ? 'PASS' : 'FAIL'],
        ['Accepted parents', model.headline.parents],
        ['Settled benefit', model.headline.coverage],
        ['Rider annual premium', model.headline.premium],
        ['Offspring portfolio', model.headline.portfolio],
      ]),
      section('Integrity checks', ['Check', 'Result', 'Detail'], (model.checks || []).map((item) => [
        item.name, item.ok ? 'PASS' : 'FAIL', item.detail || '',
      ])),
    ];
    (model.tables || []).forEach((table) => {
      sections.push(section(table.title, table.columns, table.rows));
    });
    (model.notes || []).forEach((note) => {
      sections.push(section('Note', ['Text'], [[note]]));
    });
    return '\uFEFF' + sections.join('\n\n');
  }

  root.phinsafeReportModel = phinsafeReportModel;
  root.phinsafeReportCsv = phinsafeReportCsv;
})(typeof window !== 'undefined' ? window : globalThis);
