/**
 * Actuary dashboard — ADL 3 premium release cost (risk hedge test).
 *
 * Reads GET /api/actuarial/adl3-release-cost and shows what the server
 * computed. Every figure on the screen comes from that response; nothing is
 * calculated here and nothing is written.
 */
(function (root) {
  const ENDPOINT = '/api/actuarial/adl3-release-cost';
  let chart = null;
  let requestSeq = 0;
  let lastBook = null;

  const REASONS = {
    no_annual_premium: 'No annual premium on the policy',
    no_age_on_record: 'No date of birth or age on record',
    age_outside_table: 'Age is outside the table (1–110)',
    no_expectancy_row: 'The table has no complete row for this age',
  };
  const AGE_SOURCES = {
    customer_date_of_birth: 'date of birth',
    policy_issue_age_plus_years_in_force: 'issue age + years in force',
    policy_issue_age_start_date_missing: 'issue age (no start date)',
    application_age_plus_years_in_force: 'application age + years in force',
    application_age_start_date_missing: 'application age (no start date)',
    customer_recorded_age: 'age on the customer record',
    not_recorded: 'not recorded',
  };
  const SEX_BASIS = {
    customer_record: 'customer record',
    application_record: 'application',
    policy_record: 'policy',
    average_sex_not_recorded: 'sex not recorded',
    average_records_disagree: 'records disagree',
  };
  const STOPPED = {
    age_above_table: 'age is above the table',
    no_expectancy_row: 'no expectancy row',
    no_mortality_rate: 'no mortality rate',
    no_disability_incidence_rate: 'no disability incidence rate',
  };
  const CHECK_LABELS = {
    expectancy_table_rows_complete: 'Every table row has male, female and average years',
    release_cost_is_years_times_premium: 'Release cost equals years × annual premium, recomputed from the table',
    totals_tie_to_policies: 'Totals equal the sum of the policies',
    customer_books_tie_to_total: 'Customer books add up to the total',
    every_in_force_policy_counted_once: 'Every policy in force is counted once',
    projection_year_one_ties_to_release_cost: 'Projection year 1 equals the release cost today',
    projection_ties_to_policies: 'Projection years add up to the policies',
    adjusted_risk_is_priced_risk_plus_release_cost: 'Adjusted risk equals the priced risk plus the release cost',
  };

  function authHeaders() {
    const headers = {};
    if (typeof token === 'string' && token) {
      headers.Authorization = `Bearer ${token}`;
    }
    return headers;
  }

  function html(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function money(value) {
    if (value == null) return '—';
    const n = Number(value);
    const abs = Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return (n < 0 ? '-$' : '$') + abs;
  }

  function years(value) {
    return value == null ? '—' : Number(value).toFixed(2);
  }

  function pct(value, digits) {
    return value == null ? '—' : `${Number(value).toFixed(digits == null ? 2 : digits)}%`;
  }

  function rate(value) {
    return value == null ? '—' : Number(value).toFixed(4);
  }

  function seal(value) {
    const text = String(value || '');
    return text ? `<code title="${html(text)}">${html(text.slice(0, 10))}</code>` : '—';
  }

  function el(id) {
    return document.getElementById(id);
  }

  function setHtml(id, markup) {
    const node = el(id);
    if (node) node.innerHTML = markup;
  }

  function setStatus(message, isError) {
    const node = el('adl3rc-status');
    if (!node) return;
    node.textContent = message || '';
    node.style.color = isError ? 'var(--danger)' : 'var(--text-light)';
  }

  function emptyRow(columns, message) {
    return `<tr><td colspan="${columns}" style="text-align:center;color:var(--text-light);padding:18px;">${html(message)}</td></tr>`;
  }

  function fieldValue(id) {
    const node = el(id);
    return node ? String(node.value || '').trim() : '';
  }

  function collectParams() {
    const params = new URLSearchParams();
    const add = (name, id) => {
      const value = fieldValue(id);
      if (value) params.set(name, value);
    };
    add('premium_payment_years', 'adl3rc-payment-years');
    add('projection_years', 'adl3rc-projection-years');
    add('reference_annual_premium', 'adl3rc-reference-premium');
    if (fieldValue('adl3rc-case-age') || fieldValue('adl3rc-case-premium')) {
      add('case_age', 'adl3rc-case-age');
      add('case_sex', 'adl3rc-case-sex');
      add('case_annual_premium', 'adl3rc-case-premium');
      add('case_years_paid', 'adl3rc-case-paid');
    }
    return params;
  }

  async function fetchBook(params) {
    const query = params.toString();
    const response = await fetch(query ? `${ENDPOINT}?${query}` : ENDPOINT, { headers: authHeaders() });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || !body.release_cost) {
      throw new Error(body.error || `The test could not be read (${response.status}).`);
    }
    return body.release_cost;
  }

  function renderStats(book) {
    const totals = book.totals || {};
    const summary = book.summary || {};
    const adjusted = book.adjusted_risk || {};
    const tile = (label, value, sub, tone) => `
      <div class="stat-card ${tone || ''}">
        <div class="stat-label">${html(label)}</div>
        <div class="stat-value">${html(value)}</div>
        <div style="font-size:0.72rem;color:rgba(234,241,255,0.6);margin-top:4px;">${html(sub)}</div>
      </div>`;
    setHtml('adl3rc-stats', [
      tile('Policies assessed', `${summary.policies_assessed || 0} of ${summary.policies_in_force || 0}`,
        `${summary.policies_withheld || 0} withheld · ${summary.customers_with_assessed_policy || 0} customers`),
      tile('Annual premium assessed', money(totals.annual_premium), 'Policies in force with a table row'),
      tile('Release cost (amount to hedge)', money(totals.release_cost),
        totals.release_cost_to_premium == null ? 'Years released × annual premium'
          : `${Number(totals.release_cost_to_premium).toFixed(2)} × the annual premium`, 'warning'),
      tile('Expected cost, next 12 months', money(totals.expected_release_cost_year1),
        `${pct(totals.hedge_pct_of_annual_premium)} of the annual premium`),
      tile('Expected cost, present value', money(totals.expected_release_cost_pv),
        `${(book.parameters || {}).projection_years || 0} years at ${pct(((book.parameters || {}).discount_rate || 0) * 100)}`),
      tile('Adjusted disability risk premium', money(adjusted.adjusted_disability_premium_annual),
        adjusted.disability_premium_uplift_pct == null ? 'No pinned disability premium to compare'
          : `${pct(adjusted.disability_premium_uplift_pct)} above the priced ${money(adjusted.disability_premium_annual)}`, 'success'),
    ].join(''));
  }

  function renderIntegrity(book) {
    const integrity = book.integrity || {};
    const table = book.table || {};
    const badge = el('adl3rc-integrity-badge');
    if (badge) {
      badge.textContent = integrity.ok ? 'All checks pass' : 'A check does not tie';
      badge.style.background = integrity.ok ? 'rgba(56,161,105,0.16)' : 'rgba(229,62,62,0.18)';
      badge.style.color = integrity.ok ? 'var(--success)' : 'var(--danger)';
    }
    const checks = (integrity.checks || []).map((check) => `
      <tr>
        <td style="width:90px;font-weight:700;color:${check.ok ? 'var(--success)' : 'var(--danger)'};">${check.ok ? 'Pass' : 'Fail'}</td>
        <td>${html(CHECK_LABELS[check.name] || check.name)}</td>
        <td style="color:var(--text-light);">${html(check.detail)}</td>
      </tr>`).join('');
    const parameters = book.parameters || {};
    setHtml('adl3rc-integrity', `
      <table class="data-table"><tbody>${checks}</tbody></table>
      <div style="margin-top:10px;font-size:0.82rem;color:var(--text-light);line-height:1.7;">
        Table: ${html(table.label)} · version ${html(table.tables_version)} · ${html(table.row_count)} rows ·
        fingerprint <code style="word-break:break-all;">${html(table.integrity_hash)}</code><br>
        Result seal: <code style="word-break:break-all;">${html(integrity.result_hash)}</code><br>
        Read on ${html(parameters.as_of)} · ${parameters.premium_payment_years == null
          ? 'whole expectancy released' : `${html(parameters.premium_payment_years)} years of premium payment`} ·
        writes nothing: ${book.writes_nothing ? 'yes' : 'no'}
      </div>`);
  }

  function countList(map, labels) {
    const entries = Object.entries(map || {});
    if (!entries.length) return 'none';
    return entries.map(([key, count]) => `${html((labels && labels[key]) || key)}: ${html(count)}`).join(' · ');
  }

  function renderSummary(book) {
    const summary = book.summary || {};
    const row = (label, value) => `<tr><td style="width:40%;">${html(label)}</td><td>${value}</td></tr>`;
    setHtml('adl3rc-summary', `<table class="data-table"><tbody>
      ${row('Customers registered', summary.customers_registered == null ? '—' : html(summary.customers_registered))}
      ${row('Customers with an assessed policy', html(summary.customers_with_assessed_policy))}
      ${row('Policies registered', html(summary.policies_registered))}
      ${row('Policies in force', html(summary.policies_in_force))}
      ${row('Policies assessed', html(summary.policies_assessed))}
      ${row('Policies withheld', `${html(summary.policies_withheld)} — ${countList(summary.withheld_reasons, REASONS)}`)}
      ${row('Policies not in force, by status', countList(summary.policies_not_in_force_by_status))}
      ${row('Policies on suspended test accounts (left out)', html(summary.policies_on_suspended_accounts))}
      ${row('Where the age came from', countList(summary.age_sources, AGE_SOURCES))}
      ${row('Where the sex came from', countList(summary.sex_basis, SEX_BASIS))}
    </tbody></table>`);
  }

  function renderAdjusted(book) {
    const adjusted = book.adjusted_risk || {};
    const row = (label, value) => `<tr><td style="width:55%;">${html(label)}</td><td style="font-weight:600;">${value}</td></tr>`;
    const head = (label) => `<tr><td colspan="2" style="font-weight:700;color:var(--secondary);">${html(label)}</td></tr>`;
    setHtml('adl3rc-adjusted', `<table class="data-table"><tbody>
      ${head('Premium view — annual risk cost')}
      ${row('Policies with a pinned disability premium', html(adjusted.policies_with_priced_disability_premium))}
      ${row('Policies without one (not estimated)', html(adjusted.policies_without_priced_disability_premium))}
      ${row('Disability risk premium priced at issue', money(adjusted.disability_premium_annual))}
      ${row('Expected release cost, next 12 months', money(adjusted.expected_release_cost_on_those_policies))}
      ${row('Adjusted disability risk premium', money(adjusted.adjusted_disability_premium_annual))}
      ${row('Uplift on the disability premium', pct(adjusted.disability_premium_uplift_pct))}
      ${row('Total risk premium priced at issue', money(adjusted.risk_premium_annual))}
      ${row('Adjusted total risk premium', money(adjusted.adjusted_risk_premium_annual))}
      ${row('Uplift on the total risk premium', pct(adjusted.risk_premium_uplift_pct))}
      ${head('Exposure view — amount at risk on an ADL 3 event')}
      ${row('Policies with a pinned disability sum', html(adjusted.policies_with_disability_sum))}
      ${row('Policies without one (not estimated)', html(adjusted.policies_without_disability_sum))}
      ${row('Disability sum pinned at issue', money(adjusted.disability_sum))}
      ${row('Release cost on those policies', money(adjusted.release_cost_on_those_policies))}
      ${row('Adjusted disability exposure', money(adjusted.adjusted_disability_exposure))}
      ${row('Uplift on the disability sum', pct(adjusted.risk_uplift_pct))}
    </tbody></table>`);
  }

  function renderProjection(book) {
    const rows = book.projection || [];
    const basis = el('adl3rc-projection-basis');
    if (basis) basis.textContent = book.projection_basis || '';
    setHtml('adl3rc-projection-rows', rows.length ? rows.map((row) => `
      <tr>
        <td>${html(row.year)}</td><td>${html(row.calendar_year)}</td><td>${html(row.policies_exposed)}</td>
        <td>${money(row.release_cost_at_risk)}</td><td>${money(row.expected_release_cost)}</td>
        <td>${money(row.discounted_expected_release_cost)}</td><td>${money(row.cumulative_discounted)}</td>
      </tr>`).join('') : emptyRow(7, 'No policy could be projected.'));
    drawChart(rows);
  }

  function drawChart(rows) {
    const canvas = el('adl3rc-projection-chart');
    if (!canvas || typeof Chart === 'undefined') return;
    if (chart) {
      chart.destroy();
      chart = null;
    }
    if (!rows.length) return;
    chart = new Chart(canvas, {
      data: {
        labels: rows.map((row) => row.calendar_year),
        datasets: [
          {
            type: 'bar',
            label: 'Expected release cost',
            data: rows.map((row) => row.expected_release_cost),
            backgroundColor: 'rgba(127, 178, 255, 0.55)',
            yAxisID: 'y',
          },
          {
            type: 'line',
            label: 'Release cost at risk',
            data: rows.map((row) => row.release_cost_at_risk),
            borderColor: '#e3bf6f',
            backgroundColor: 'transparent',
            tension: 0.2,
            pointRadius: 0,
            yAxisID: 'y1',
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#cbd5e0' } } },
        scales: {
          x: { ticks: { color: '#a0aec0' }, grid: { color: 'rgba(255,255,255,0.05)' } },
          y: {
            position: 'left',
            title: { display: true, text: 'Expected ($)', color: '#a0aec0' },
            ticks: { color: '#a0aec0' },
            grid: { color: 'rgba(255,255,255,0.05)' },
          },
          y1: {
            position: 'right',
            title: { display: true, text: 'At risk ($)', color: '#a0aec0' },
            ticks: { color: '#a0aec0' },
            grid: { drawOnChartArea: false },
          },
        },
      },
    });
  }

  function renderBands(book) {
    const rows = book.by_age_band || [];
    setHtml('adl3rc-band-rows', rows.length ? rows.map((row) => `
      <tr>
        <td>${html(row.age_band)}</td><td>${html(row.sex_used)}_years</td><td>${html(row.policies)}</td>
        <td>${money(row.annual_premium)}</td><td>${years(row.premium_weighted_released_years)}</td>
        <td>${money(row.release_cost)}</td>
      </tr>`).join('') : emptyRow(6, 'No policy assessed.'));
  }

  function renderCustomers(book) {
    const rows = book.customers || [];
    const count = el('adl3rc-customers-count');
    if (count) count.textContent = `${rows.length} of ${book.customers_total || 0} customers, largest hedge first`;
    setHtml('adl3rc-customer-rows', rows.length ? rows.map((row) => `
      <tr>
        <td><strong>${html(row.customer_name || row.customer_id)}</strong><br><span style="color:var(--text-light);font-size:0.78rem;">${html(row.customer_id)}</span></td>
        <td>${html(row.policies)}${row.withheld_policies ? ` <span style="color:var(--warning);">(+${html(row.withheld_policies)} withheld)</span>` : ''}</td>
        <td>${money(row.annual_premium)}</td><td style="font-weight:700;">${money(row.release_cost)}</td>
        <td>${money(row.expected_release_cost_year1)}</td><td>${money(row.expected_release_cost_pv)}</td>
        <td>${seal(row.integrity_hash)}</td>
        <td><button class="btn btn-small btn-outline" data-adl3rc-customer="${html(row.customer_id)}">Open book</button></td>
      </tr>`).join('') : emptyRow(8, 'No customer has an assessed policy.'));
    document.querySelectorAll('[data-adl3rc-customer]').forEach((button) => {
      button.addEventListener('click', () => openCustomer(button.getAttribute('data-adl3rc-customer')));
    });
  }

  function policyRow(row) {
    return `
      <tr>
        <td><strong>${html(row.policy_id)}</strong><br><span style="color:var(--text-light);font-size:0.78rem;">${html(row.policy_type)}</span></td>
        <td>${html(row.customer_name || row.customer_id)}</td>
        <td>${html(row.attained_age)}<br><span style="color:var(--text-light);font-size:0.78rem;">${html(AGE_SOURCES[row.age_source] || row.age_source)}</span></td>
        <td>${html(row.sex_used)}_years<br><span style="color:var(--text-light);font-size:0.78rem;">${html(SEX_BASIS[row.sex_basis] || row.sex_basis)}</span></td>
        <td>${money(row.annual_premium)}</td><td>${html(row.years_paid)}</td>
        <td>${years(row.expectancy_years)}</td><td>${years(row.released_years)}</td>
        <td style="font-weight:700;">${money(row.release_cost)}</td>
        <td>${rate(row.disability_incidence_ix)}</td><td>${money(row.expected_release_cost_year1)}</td>
        <td>${row.disability_premium_annual == null ? `<span style="color:var(--text-light);">${row.priced_risk_basis === 'pin_seal_broken' ? 'seal broken' : 'not pinned'}</span>` : money(row.disability_premium_annual)}</td>
        <td>${money(row.adjusted_disability_premium_annual)}</td>
        <td>${pct(row.disability_premium_uplift_pct)}</td><td>${seal(row.integrity_hash)}</td>
      </tr>`;
  }

  function renderPolicies(book) {
    const rows = book.policies || [];
    const count = el('adl3rc-policies-count');
    if (count) count.textContent = `${book.policies_listed || 0} of ${book.policies_total || 0} assessed policies`;
    setHtml('adl3rc-policy-rows', rows.length ? rows.map(policyRow).join('') : emptyRow(15, 'No policy assessed.'));
  }

  function renderWithheld(book) {
    const rows = book.withheld || [];
    setHtml('adl3rc-withheld-rows', rows.length ? rows.map((row) => `
      <tr>
        <td>${html(row.policy_id)}</td><td>${html(row.customer_name || row.customer_id)}</td>
        <td>${money(row.annual_premium)}</td><td>${row.attained_age == null ? '—' : html(row.attained_age)}</td>
        <td>${html(REASONS[row.reason] || row.reason)}</td>
      </tr>`).join('') : emptyRow(5, 'Nothing is withheld.'));
  }

  function renderReference(book) {
    const reference = book.reference || {};
    const note = el('adl3rc-reference-note');
    if (note) {
      const term = (book.parameters || {}).premium_payment_years;
      note.textContent = `Annual premium ${money(reference.annual_premium)} · ${term == null
        ? 'whole expectancy' : `${term} years of premium payment, none paid yet`}`;
    }
    const rows = reference.rows || [];
    setHtml('adl3rc-reference-rows', rows.map((row) => `
      <tr>
        <td>${html(row.age)}</td>
        <td>${years(row.male_years)}</td><td>${money(row.male_release_cost)}</td>
        <td>${years(row.female_years)}</td><td>${money(row.female_release_cost)}</td>
        <td>${years(row.average_years)}</td><td>${money(row.average_release_cost)}</td>
      </tr>`).join(''));
  }

  function renderCase(book) {
    const result = book.case;
    if (!result) {
      setHtml('adl3rc-case', '<span style="color:var(--text-light);font-size:0.85rem;">Enter an age and an annual premium to price one case on the same table.</span>');
      return;
    }
    if (result.status !== 'assessed') {
      setHtml('adl3rc-case', `<div class="alert alert-warning">Withheld: ${html(REASONS[result.reason] || result.reason)}.</div>`);
      return;
    }
    const stopped = result.projection_stopped
      ? ` The projection stops at age ${html(result.projection_stopped.age)} (${html(STOPPED[result.projection_stopped.reason] || result.projection_stopped.reason)}).`
      : '';
    setHtml('adl3rc-case', `<table class="data-table"><tbody>
      <tr><td style="width:55%;">Table years at age ${html(result.attained_age)} (${html(result.sex_used)}_years)</td><td>${years(result.expectancy_years)}</td></tr>
      <tr><td>Years released</td><td>${years(result.released_years)}${result.remaining_payment_years == null ? '' : ` (premium still due for ${html(result.remaining_payment_years)} years)`}</td></tr>
      <tr><td>Release cost = years released × ${money(result.annual_premium)}</td><td style="font-weight:700;">${money(result.release_cost)}</td></tr>
      <tr><td>Disability incidence i(x) / mortality q(x)</td><td>${rate(result.disability_incidence_ix)} / ${rate(result.mortality_qx)}</td></tr>
      <tr><td>Expected release cost, next 12 months</td><td>${money(result.expected_release_cost_year1)} (${pct(result.hedge_pct_of_annual_premium)} of the premium)</td></tr>
      <tr><td>Expected release cost, present value over ${html(result.projection_years_run)} years</td><td>${money(result.expected_release_cost_pv)}</td></tr>
    </tbody></table><div style="font-size:0.82rem;color:var(--text-light);margin-top:6px;">${stopped}</div>`);
  }

  function render(book) {
    lastBook = book;
    renderStats(book);
    renderIntegrity(book);
    renderSummary(book);
    renderAdjusted(book);
    renderProjection(book);
    renderBands(book);
    renderCustomers(book);
    renderPolicies(book);
    renderWithheld(book);
    renderReference(book);
    renderCase(book);
  }

  async function load() {
    const seq = ++requestSeq;
    setStatus('Reading the table and the registered policies…');
    try {
      const book = await fetchBook(collectParams());
      if (seq !== requestSeq) return;
      render(book);
      setHtml('adl3rc-customer-book', '');
      setStatus(`Read on ${(book.parameters || {}).as_of || ''}. Nothing was written.`);
    } catch (error) {
      if (seq !== requestSeq) return;
      setStatus(error.message || 'The test could not be read.', true);
    }
  }

  async function openCustomer(customerId) {
    const host = el('adl3rc-customer-book');
    if (!host || !customerId) return;
    host.innerHTML = '<span style="color:var(--text-light);">Reading the customer book…</span>';
    try {
      const params = collectParams();
      ['case_age', 'case_sex', 'case_annual_premium', 'case_years_paid', 'reference_annual_premium']
        .forEach((name) => params.delete(name));
      params.set('customer_id', customerId);
      const book = await fetchBook(params);
      const policies = book.policies || [];
      const totals = book.totals || {};
      const name = (policies[0] && policies[0].customer_name) || customerId;
      const blocks = policies.map((row) => {
        const projection = (row.projection || []).map((year) => `
          <tr>
            <td>${html(year.year)}</td><td>${html(year.calendar_year)}</td><td>${html(year.attained_age)}</td>
            <td>${years(year.expectancy_years)}</td><td>${years(year.released_years)}</td>
            <td>${money(year.release_cost)}</td><td>${rate(year.disability_incidence_ix)}</td>
            <td>${rate(year.mortality_qx)}</td><td>${Number(year.in_force_probability).toFixed(4)}</td>
            <td>${money(year.expected_release_cost)}</td><td>${money(year.discounted_expected_release_cost)}</td>
          </tr>`).join('');
        const stopped = row.projection_stopped
          ? `<div style="font-size:0.82rem;color:var(--warning);margin-top:6px;">The projection stops at age ${html(row.projection_stopped.age)}: ${html(STOPPED[row.projection_stopped.reason] || row.projection_stopped.reason)}.</div>`
          : '';
        return `
          <div style="margin-top:14px;">
            <div style="font-weight:700;margin-bottom:6px;">${html(row.policy_id)} · ${money(row.annual_premium)} a year ·
              age ${html(row.attained_age)} · ${html(row.sex_used)}_years · release cost ${money(row.release_cost)} · seal ${seal(row.integrity_hash)}</div>
            <div style="max-height:300px;overflow:auto;">
              <table class="data-table">
                <thead><tr><th>Year</th><th>Calendar year</th><th>Age</th><th>Table years</th><th>Years released</th>
                  <th>Release cost</th><th>i(x)</th><th>q(x)</th><th>In force</th><th>Expected</th><th>Discounted</th></tr></thead>
                <tbody>${projection || emptyRow(11, 'No year could be projected.')}</tbody>
              </table>
            </div>${stopped}
          </div>`;
      }).join('');
      const withheld = (book.withheld || []).map((row) => `
        <div style="font-size:0.85rem;color:var(--warning);margin-top:8px;">${html(row.policy_id)} is withheld: ${html(REASONS[row.reason] || row.reason)}.</div>`).join('');
      host.innerHTML = `
        <div class="alert alert-info" style="margin-bottom:0;">
          <strong>${html(name)}</strong> (${html(customerId)}) — ${policies.length} policies assessed ·
          annual premium ${money(totals.annual_premium)} · release cost ${money(totals.release_cost)} ·
          expected next 12 months ${money(totals.expected_release_cost_year1)} · present value ${money(totals.expected_release_cost_pv)} ·
          checks ${(book.integrity || {}).ok ? 'pass' : 'do not tie'} · seal ${seal((book.integrity || {}).result_hash)}
        </div>${blocks}${withheld}`;
      host.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } catch (error) {
      host.innerHTML = `<div class="alert alert-danger">${html(error.message || 'The customer book could not be read.')}</div>`;
    }
  }

  function reset() {
    ['adl3rc-payment-years', 'adl3rc-reference-premium', 'adl3rc-case-age', 'adl3rc-case-premium'].forEach((id) => {
      const node = el(id);
      if (node) node.value = '';
    });
    const projection = el('adl3rc-projection-years');
    if (projection) projection.value = '30';
    const paid = el('adl3rc-case-paid');
    if (paid) paid.value = '0';
    const sex = el('adl3rc-case-sex');
    if (sex) sex.value = 'average';
    load();
  }

  root.PhinsAdl3ReleaseCost = { load, reset, openCustomer, last: () => lastBook };
})(window);
