/**
 * Annual-report revenue centers.
 *
 * PHINS Unified and PhinSafe restate a published actuarial snapshot.
 * Every other platform center is an outline and a forecast method only.
 * This filing does not issue a financial statement for any center here:
 * platform profit, margin, and cash are left unpublished until a ledger
 * is bound. No missing amount is written as zero.
 */
(function (root) {
  const STATEMENT_METHOD = 'This section does not issue a second set of financial statements. Actuarial centers restate the published snapshot. Other centers stay at outline and forecast method until a ledger is bound.';

  const UNIFIED_OUTLINE = 'Adjustable life-and-disability contract. Mortality pays the attained-age life sum. Disability pays the age-banded sum. The savings add-on is a deposit, not revenue.';
  const UNIFIED_FORECAST = 'Year-1 claims are the life sum times q(x) plus the disability sum times i(x). Later years follow the bound reserve projection. This section does not reprice.';
  const PHINSAFE_OUTLINE = 'Child catastrophe hedge. Permanent settlement at one fifth of each attached parent policy. Parents join from age 18 through a community maximum below the simulator maximum age. A first pregnancy is covered only after one year.';

  function copyAmount(value) {
    if (value == null || value === '') return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function centsOf(row, key) {
    if (!row) return null;
    const raw = row[key + '_cents'];
    if (raw == null || raw === '') return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }

  function textOrNull(value) {
    if (value == null || value === '') return null;
    return String(value);
  }

  function pushFigure(rows, label, value, kind) {
    if (value == null || value === '') return;
    rows.push({ label: label, value: value, kind: kind });
  }

  function platformCenter(id, name, outline, forecastMethod) {
    return {
      id: id,
      name: name,
      kind: 'platform',
      reporting: 'outline_only',
      financial_reporting: 'not_bound',
      financial_statement: false,
      figures: null,
      figure_rows: [],
      forecast: [],
      outline: outline,
      forecast_method: forecastMethod,
      method: STATEMENT_METHOD,
    };
  }

  const BUILT_IN_PLATFORMS = [
    platformCenter(
      'health_wallet_supplier_margin',
      'Health wallet versus supplier margin',
      'Customers pay suppliers from the health wallet. The margin is the contractual take on a settled order against the wallet debit.',
      'The forecast would be bound wallet orders times the contracted margin. No amount is stated until a ledger is bound.'
    ),
    platformCenter(
      'investments_markup',
      'Investments markup',
      'The markup is the spread between the customer price and the underlying investment. It is not an insurance premium.',
      'The forecast would be assets under management times the published markup. No assets and no rate are stated.'
    ),
    platformCenter(
      'technology_sales',
      'Technology sales',
      'Partner technology and software fees, kept separate from insurance premium.',
      'The forecast would be seats times the published fee. No fee schedule is bound.'
    ),
  ];

  function portfolioVerifies(book, portfolio) {
    if (!book || !portfolio) return false;
    if (!book.document_hash) return false;
    if (String(portfolio.source_book_hash || '') !== String(book.document_hash)) return false;
    if (String(portfolio.simulation_id || '') !== String(book.simulation_id || '')) return false;
    if (!(portfolio.integrity && portfolio.integrity.all_checks_pass)) return false;
    return true;
  }

  function scheduleTrusts(book, portfolio) {
    if (!portfolioVerifies(book, portfolio)) return false;
    const schedule = portfolio.schedule || [];
    const totals = portfolio.totals || {};
    const face = centsOf(book.rider_book || {}, 'coverage');
    if (!schedule.length || face == null) return false;
    let premium = 0;
    let claims = 0;
    let savings = 0;
    for (let i = 0; i < schedule.length; i += 1) {
      const row = schedule[i];
      const rowPremium = centsOf(row, 'premium');
      const rowClaims = centsOf(row, 'expected_claims');
      const rowSavings = centsOf(row, 'savings');
      const rowRisk = centsOf(row, 'risk_premium');
      const rowFace = centsOf(row, 'benefit_in_force');
      if (rowPremium == null || rowClaims == null || rowSavings == null || rowRisk == null || rowFace == null) return false;
      if (rowRisk + rowSavings !== rowPremium) return false;
      if (rowFace !== face) return false;
      premium += rowPremium;
      claims += rowClaims;
      savings += rowSavings;
    }
    return centsOf(totals, 'premium') === premium
      && centsOf(totals, 'expected_claims') === claims
      && centsOf(totals, 'savings_account') === savings;
  }

  function displayDollars(row, key) {
    if (row && row[key] != null && row[key] !== '' && Number.isFinite(Number(row[key]))) {
      return Number(row[key]);
    }
    const cents = centsOf(row, key);
    return cents == null ? null : cents / 100;
  }

  function unifiedCenter(unified) {
    const base = {
      id: 'phins_unified',
      name: 'PHINS Unified — adjustable life-and-disability',
      kind: 'actuarial',
      financial_statement: false,
      forecast: [],
      outline: UNIFIED_OUTLINE,
      forecast_method: UNIFIED_FORECAST,
      method: STATEMENT_METHOD,
    };
    if (!unified || !unified.simulation_id) {
      return Object.assign(base, {
        reporting: 'not_bound',
        financial_reporting: 'not_bound',
        figures: null,
        figure_rows: [],
      });
    }
    const figures = {
      simulation_id: String(unified.simulation_id),
      product_id: textOrNull(unified.product_id) || 'phins_pure_risk_adjustable',
      tables_version: textOrNull(unified.tables_version),
      accepted: copyAmount(unified.accepted),
      coverage: copyAmount(unified.coverage),
      annual_premium: copyAmount(unified.annual_premium),
      annual_expected_claims: copyAmount(unified.annual_expected_claims),
      year1_loss_ratio: unified.year1_loss_ratio == null || unified.year1_loss_ratio === ''
        ? null
        : copyAmount(unified.year1_loss_ratio),
    };
    const figureRows = [];
    pushFigure(figureRows, 'Simulation', figures.simulation_id, 'text');
    pushFigure(figureRows, 'Product', figures.product_id, 'text');
    pushFigure(figureRows, 'Tables version', figures.tables_version, 'text');
    pushFigure(figureRows, 'Accepted lives', figures.accepted, 'count');
    pushFigure(figureRows, 'Coverage in force', figures.coverage, 'money');
    pushFigure(figureRows, 'Annual premium', figures.annual_premium, 'money');
    pushFigure(figureRows, 'Annual expected claims', figures.annual_expected_claims, 'money');
    pushFigure(figureRows, 'Year-1 loss ratio', figures.year1_loss_ratio, 'pct');
    return Object.assign(base, {
      reporting: 'bound',
      financial_reporting: 'not_issued',
      figures: figures,
      figure_rows: figureRows,
    });
  }

  function phinsafeCenter(unified, book, portfolio) {
    const base = {
      id: 'phinsafe',
      name: 'PhinSafe',
      kind: 'actuarial',
      financial_statement: false,
      outline: PHINSAFE_OUTLINE,
      method: STATEMENT_METHOD,
      figures: null,
      figure_rows: [],
      forecast: [],
    };
    if (!book) {
      return Object.assign(base, {
        reporting: 'not_bound',
        financial_reporting: 'not_bound',
        forecast_method: 'Run the PhinSafe test on the bound simulation to publish this center. Develop the offspring portfolio to publish the year-by-year forecast.',
      });
    }
    const simId = unified && unified.simulation_id ? String(unified.simulation_id) : '';
    if (!simId || String(book.simulation_id || '') !== simId) {
      return Object.assign(base, {
        reporting: 'withheld',
        financial_reporting: 'withheld',
        forecast_method: 'The book belongs to a different simulation, so its figures are withheld. This section does not mix books.',
      });
    }
    const rider = book.rider_book || {};
    const figures = {
      simulation_id: String(book.simulation_id || ''),
      document_hash: String(book.document_hash || ''),
      product_id: String(book.product_id || 'phinsafe'),
      accepted_parents: copyAmount(rider.accepted_parents),
      coverage: copyAmount(rider.coverage),
      annual_premium: copyAmount(rider.annual_premium),
      savings_premium: copyAmount(rider.savings_premium),
      annual_expected_claims: rider.annual_expected_claims == null || rider.annual_expected_claims === ''
        ? null
        : copyAmount(rider.annual_expected_claims),
      loss_ratio_pct: rider.loss_ratio_pct == null || rider.loss_ratio_pct === ''
        ? null
        : copyAmount(rider.loss_ratio_pct),
    };
    const figureRows = [];
    pushFigure(figureRows, 'Simulation', figures.simulation_id, 'text');
    pushFigure(figureRows, 'Document hash', figures.document_hash, 'text');
    pushFigure(figureRows, 'Product', figures.product_id, 'text');
    pushFigure(figureRows, 'Accepted parents', figures.accepted_parents, 'count');
    pushFigure(figureRows, 'Settled benefit', figures.coverage, 'money');
    pushFigure(figureRows, 'Annual premium', figures.annual_premium, 'money');
    pushFigure(figureRows, 'Savings deposit', figures.savings_premium, 'money');
    pushFigure(figureRows, 'Annual expected claims', figures.annual_expected_claims, 'money');
    pushFigure(figureRows, 'Loss ratio', figures.loss_ratio_pct, 'pct');
    let forecast = [];
    let forecastMethod = 'Develop the offspring portfolio to publish the year-by-year forecast. This section does not reprice.';
    if (portfolio && !scheduleTrusts(book, portfolio)) {
      forecastMethod = 'An offspring portfolio was supplied, but it does not verify against this book, so the year-by-year forecast is withheld.';
    } else if (portfolio && scheduleTrusts(book, portfolio)) {
      const schedule = portfolio.schedule || [];
      forecast = schedule.slice(0, 40).map((row) => ({
        year: row.policy_year != null ? row.policy_year : null,
        age: row.offspring_age != null ? row.offspring_age : null,
        premium: displayDollars(row, 'premium'),
        expected_claims: displayDollars(row, 'expected_claims'),
        savings: displayDollars(row, 'savings'),
      }));
      forecastMethod = 'The year-by-year forecast is the published offspring schedule, copied from that portfolio. This section does not reprice.';
      if (schedule.length > 40) {
        forecastMethod += ' The filing shows the first 40 years of the published schedule.';
      }
    }
    return Object.assign(base, {
      reporting: 'bound',
      financial_reporting: 'not_issued',
      figures: figures,
      figure_rows: figureRows,
      forecast: forecast,
      forecast_method: forecastMethod,
    });
  }

  function extraPlatforms(list) {
    const reserved = {
      phins_unified: true,
      phinsafe: true,
      health_wallet_supplier_margin: true,
      investments_markup: true,
      technology_sales: true,
    };
    return (list || []).map((item) => {
      const id = String((item && item.id) || '').trim();
      if (!id || reserved[id]) return null;
      return platformCenter(
        id,
        String((item && item.name) || id),
        String((item && item.outline) || 'Outline only. No ledger is bound, so this filing states the forecast method and does not publish an amount.'),
        String((item && item.forecast_method) || 'No forecast is published until a ledger for this center is bound.')
      );
    }).filter(Boolean);
  }

  function buildRevenueCenters(input) {
    const source = input || {};
    const unified = source.unified || null;
    const book = source.phinsafe || null;
    const portfolio = source.phinsafePortfolio || null;
    const centers = [unifiedCenter(unified), phinsafeCenter(unified, book, portfolio)]
      .concat(BUILT_IN_PLATFORMS.map((center) => Object.assign({}, center)))
      .concat(extraPlatforms(source.platforms));
    const checks = [];
    const platformClean = centers.filter((center) => center.kind === 'platform').every((center) => (
      center.figures == null
      && Array.isArray(center.forecast)
      && center.forecast.length === 0
      && center.financial_statement === false
      && center.financial_reporting === 'not_bound'
      && center.reporting === 'outline_only'
    ));
    checks.push({
      name: 'Platform revenue centers publish outline and forecast method only',
      ok: platformClean,
      detail: platformClean ? 'no figures' : 'a platform center carried a figure',
    });

    const unifiedRow = centers[0];
    let unifiedOk = false;
    let unifiedDetail = 'not_bound';
    if (!unified || !unified.simulation_id) {
      unifiedOk = unifiedRow.reporting === 'not_bound' && unifiedRow.figures == null && unifiedRow.forecast.length === 0;
      unifiedDetail = 'not_bound';
    } else {
      const figures = unifiedRow.figures || {};
      unifiedOk = unifiedRow.reporting === 'bound'
        && unifiedRow.financial_statement === false
        && figures.simulation_id === String(unified.simulation_id)
        && figures.accepted === copyAmount(unified.accepted)
        && figures.coverage === copyAmount(unified.coverage)
        && figures.annual_premium === copyAmount(unified.annual_premium)
        && figures.annual_expected_claims === copyAmount(unified.annual_expected_claims)
        && figures.year1_loss_ratio === (unified.year1_loss_ratio == null || unified.year1_loss_ratio === ''
          ? null
          : copyAmount(unified.year1_loss_ratio));
      unifiedDetail = unifiedOk ? String(unified.simulation_id) : 'figures drifted from the bound simulation';
    }
    checks.push({
      name: 'PHINS Unified revenue center matches the bound simulation',
      ok: unifiedOk,
      detail: unifiedDetail,
    });

    const safeRow = centers[1];
    let safeOk = false;
    let safeDetail = 'not_bound';
    if (!book) {
      safeOk = safeRow.reporting === 'not_bound' && safeRow.figures == null && safeRow.forecast.length === 0;
      safeDetail = 'not_bound';
    } else if (!unified || !unified.simulation_id || String(book.simulation_id || '') !== String(unified.simulation_id)) {
      safeOk = safeRow.reporting === 'withheld' && safeRow.figures == null && safeRow.forecast.length === 0;
      safeDetail = 'withheld';
    } else {
      safeOk = safeRow.reporting === 'bound'
        && safeRow.financial_statement === false
        && safeRow.figures
        && safeRow.figures.document_hash === String(book.document_hash || '')
        && safeRow.figures.simulation_id === String(book.simulation_id || '');
      safeDetail = safeOk ? String(book.document_hash || '') : 'book was not copied';
    }
    checks.push({
      name: 'PhinSafe revenue center is the published book',
      ok: safeOk,
      detail: safeDetail,
    });

    let forecastOk = true;
    let forecastDetail = 'not_bound';
    if (!book) {
      forecastDetail = 'not_bound';
    } else if (safeRow.reporting === 'withheld') {
      forecastDetail = 'withheld';
    } else if (!portfolio) {
      forecastDetail = 'forecast not published';
      forecastOk = safeRow.forecast.length === 0;
    } else if (!scheduleTrusts(book, portfolio)) {
      forecastOk = safeRow.forecast.length === 0;
      forecastDetail = forecastOk
        ? 'offspring portfolio does not verify against the published book'
        : 'a forecast was published from a portfolio that does not verify';
      if (forecastOk) forecastOk = false;
    } else {
      const first = (portfolio.schedule || [])[0] || {};
      const published = safeRow.forecast[0] || {};
      forecastOk = safeRow.forecast.length === Math.min(40, (portfolio.schedule || []).length)
        && published.premium === displayDollars(first, 'premium')
        && published.expected_claims === displayDollars(first, 'expected_claims')
        && published.savings === displayDollars(first, 'savings');
      forecastDetail = forecastOk ? 'schedule copied' : 'forecast drifted from the published schedule';
    }
    checks.push({
      name: 'PhinSafe forecast is the published offspring schedule',
      ok: forecastOk,
      detail: forecastDetail,
    });

    return {
      method: STATEMENT_METHOD,
      centers: centers,
      checks: checks,
    };
  }

  root.buildRevenueCenters = buildRevenueCenters;
})(typeof window !== 'undefined' ? window : globalThis);
