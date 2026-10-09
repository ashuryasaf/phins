/**
 * Actuary dashboard — LTC residential services market & hedging strategy
 * (Research & Audit).
 *
 * Reads the study controls, calls /api/actuarial/ltc-residential-research,
 * and fills KPIs, narrative, Chart.js canvases, tables, the media gallery
 * and the animated 50+50-year timeline player (which can be recorded to a
 * WebM file in the browser — no third-party embed, CSP stays untouched).
 * Downloads reuse the same control set so the file matches the screen.
 */
(function (root) {
  let lastPack = null;
  let inflight = null;
  const charts = {};
  const player = { timer: null, frame: 0, recorder: null, chunks: [], playing: false };

  function authHeaders() {
    const headers = {};
    if (typeof token === 'string' && token) {
      headers.Authorization = `Bearer ${token}`;
    }
    return headers;
  }

  function money(value, digits) {
    const n = Number(value || 0);
    const d = digits == null ? 0 : digits;
    return (n < 0 ? '-$' : '$') + Math.abs(n).toLocaleString('en-US', {
      minimumFractionDigits: d,
      maximumFractionDigits: d,
    });
  }

  function bn(value, digits) {
    if (value == null || value === '') return '—';
    const d = digits == null ? 1 : digits;
    return `$${Number(value).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })}bn`;
  }

  function pct(value, digits) {
    if (value == null || value === '') return '—';
    const d = digits == null ? 1 : digits;
    return `${Number(value).toFixed(d)}%`;
  }

  function num(value, digits) {
    if (value == null || value === '') return '—';
    const d = digits == null ? 1 : digits;
    return Number(value).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  }

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function basisBadge(basis) {
    const b = String(basis || '').toLowerCase();
    const tone = b === 'published' ? '#2f855a' : b === 'derived' ? '#2b6cb0' : b === 'projection' ? '#b7791f' : b === 'model' ? '#805ad5' : '#718096';
    return b ? `<span class="ltcres-basis" style="border-color:${tone};color:${tone};">${esc(b)}</span>` : '';
  }

  function setStatus(message, isError) {
    const el = document.getElementById('ltcres-status');
    if (!el) return;
    el.textContent = message || '';
    el.style.color = isError ? 'var(--danger)' : 'var(--text-light)';
  }

  const DEFAULTS = {
    'ltcres-region': 'us',
    'ltcres-scenario': 'baseline',
    'ltcres-forecast-end': '2075',
    'ltcres-cost-infl': '3.5',
    'ltcres-gdp-growth': '3.5',
    'ltcres-healthy': '0.5',
    'ltcres-home-target': '',
    'ltcres-lives': '10000',
    'ltcres-age-min': '30',
    'ltcres-age-max': '85',
    'ltcres-cover': '60000',
    'ltcres-adl': '3',
    'ltcres-capital': '25000000',
    'ltcres-allocation': 'balanced',
    'ltcres-stress': '30',
    'ltcres-discount': '6',
    'ltcres-som': '0.5',
  };

  function val(id) {
    const el = document.getElementById(id);
    return el ? el.value : DEFAULTS[id];
  }

  function collectParams() {
    const params = {
      region: val('ltcres-region') || 'us',
      scenario: val('ltcres-scenario') || 'baseline',
      forecast_end: val('ltcres-forecast-end') || '2075',
      care_cost_inflation_pct: val('ltcres-cost-infl') || '3.5',
      gdp_growth_pct: val('ltcres-gdp-growth') || '3.5',
      healthy_ageing_pct: val('ltcres-healthy') || '0.5',
      lives: val('ltcres-lives') || '10000',
      age_min: val('ltcres-age-min') || '30',
      age_max: val('ltcres-age-max') || '85',
      ltc_annual_cover: val('ltcres-cover') || '60000',
      adl_threshold: val('ltcres-adl') || '3',
      hedge_capital: val('ltcres-capital') || '25000000',
      hedge_allocation: val('ltcres-allocation') || 'balanced',
      incidence_stress_pct: val('ltcres-stress') || '30',
      discount_rate_pct: val('ltcres-discount') || '6',
      som_share_pct: val('ltcres-som') || '0.5',
    };
    const target = val('ltcres-home-target');
    if (target !== undefined && target !== null && String(target).trim() !== '') {
      params.home_care_share_target_pct = target;
    }
    return params;
  }

  function queryString(extra) {
    const params = Object.assign(collectParams(), extra || {});
    const qs = new URLSearchParams();
    Object.keys(params).forEach((key) => {
      if (params[key] !== undefined && params[key] !== null && params[key] !== '') {
        qs.set(key, String(params[key]));
      }
    });
    return qs.toString();
  }

  function fillBody(tableId, html) {
    const table = document.getElementById(tableId);
    const body = table && table.tBodies && table.tBodies[0];
    if (body) body.innerHTML = html;
  }

  function emptyRow(cols, message) {
    return `<tr><td colspan="${cols}" style="text-align:center;color:var(--text-light);">${esc(message)}</td></tr>`;
  }

  function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  // ---------------------------------------------------------------- KPIs
  function renderKpis(pack) {
    const k = pack.kpis || {};
    setText('ltcres-kpi-spend-gdp', k.region_ltc_spend_gdp_pct == null ? '—' : pct(k.region_ltc_spend_gdp_pct, 2));
    setText('ltcres-kpi-public', k.region_public_share_pct == null ? '—' : pct(k.region_public_share_pct, 0));
    setText('ltcres-kpi-tam-now', k.tam_2025_usd_bn == null ? '—' : bn(k.tam_2025_usd_bn, 0));
    setText('ltcres-kpi-tam-end', k.tam_end_usd_bn == null ? '—' : bn(k.tam_end_usd_bn, 0));
    setText('ltcres-kpi-som-end', k.som_end_usd_bn == null ? '—' : bn(k.som_end_usd_bn, 1));
    setText('ltcres-kpi-hedge', k.hedge_ratio_pct == null ? '—' : pct(k.hedge_ratio_pct, 1));
    const endLabel = document.getElementById('ltcres-kpi-end-year');
    if (endLabel) endLabel.textContent = k.end_year || '2075';
    const endLabel2 = document.getElementById('ltcres-kpi-end-year-2');
    if (endLabel2) endLabel2.textContent = k.end_year || '2075';
  }

  function renderNarrative(pack) {
    const el = document.getElementById('ltcres-narrative');
    if (!el) return;
    const lines = pack.narrative || [];
    el.innerHTML = lines.map((line) => `<p style="margin-bottom:8px;">${esc(line)}</p>`).join('')
      || '<p style="color:var(--text-light);">No narrative.</p>';
    const scen = document.getElementById('ltcres-scenario-note');
    if (scen) {
      scen.textContent = `${pack.scenario_label || ''} — ${pack.scenario_note || ''} Home-share target ${num(pack.home_share_target_pct, 1)}%. ${pack.region_note || ''}`;
    }
  }

  function renderSources(pack) {
    const el = document.getElementById('ltcres-sources');
    if (!el) return;
    el.innerHTML = (pack.sources || []).map((src) => {
      const href = src.url && String(src.url).startsWith('http')
        ? `<a href="${esc(src.url)}" target="_blank" rel="noopener">${esc(src.source)}</a>`
        : `<strong>${esc(src.source)}</strong>`;
      return `<li><code>${esc(src.id)}</code> · ${href} · ${esc(src.published_year || '')} · ${esc(src.period_covered || '')}<br>`
        + `<span style="color:var(--text-light);">${esc(src.headline_metric || '')} ${esc(src.relevance || '')}</span></li>`;
    }).join('');
  }

  // ---------------------------------------------------------------- tables
  function renderMarketStructure(rows) {
    if (!rows || !rows.length) { fillBody('ltcres-structure-table', emptyRow(10, 'No rows.')); return; }
    fillBody('ltcres-structure-table', rows.map((r) => `
      <tr>
        <td><strong>${esc(r.label)}</strong></td>
        <td>${pct(r.ltc_spend_gdp_pct, 2)} <span style="color:var(--text-light);">(${esc(r.ltc_spend_year)})</span> ${basisBadge(r.ltc_spend_basis)}</td>
        <td>${bn(r.ltc_spend_2025_usd_bn, 0)}</td>
        <td>${pct(r.public_share_pct, 0)}</td>
        <td>${pct(r.residential_recipient_share_pct, 0)} / ${pct(r.home_recipient_share_pct, 0)}</td>
        <td>${num(r.beds_per_1000_65plus, 0)}</td>
        <td>${num(r.workers_per_100_65plus, 1)}</td>
        <td>${pct(r.for_profit_share_pct, 0)}</td>
        <td>${pct(r.pop80_share_2025_pct, 1)} → ${pct(r.pop80_share_2050_pct, 1)}</td>
        <td style="color:var(--text-light);">${esc(r.note)}</td>
      </tr>`).join(''));
  }

  function renderSettingComparison(rows) {
    if (!rows || !rows.length) { fillBody('ltcres-settings-table', emptyRow(11, 'No rows.')); return; }
    fillBody('ltcres-settings-table', rows.map((r) => `
      <tr>
        <td><strong>${esc(r.label)}</strong><br><span style="color:var(--text-light);">${esc(r.typical_acuity)}</span></td>
        <td>${r.us_share_of_facilities_pct == null ? '—' : pct(r.us_share_of_facilities_pct, 0)}</td>
        <td>${r.typical_occupancy_pct == null ? '—' : pct(r.typical_occupancy_pct, 0)}</td>
        <td>${money(r.median_annual_cost_usd)}</td>
        <td>${r.nurse_hprd_typical == null ? '—' : `${num(r.nurse_hprd_typical, 1)} (RN ${num(r.rn_hprd_typical, 2)})`}</td>
        <td>${pct(r.medicaid_share_pct, 0)}</td>
        <td>${r.deficiencies_per_survey == null ? '—' : num(r.deficiencies_per_survey, 1)}</td>
        <td>${pct(r.ebitdar_margin_pct, 0)}</td>
        <td>${pct(r.labor_cost_share_pct, 0)}</td>
        <td>${esc(r.capital_intensity)} / ${esc(r.regulatory_intensity)}</td>
        <td style="color:var(--text-light);">${esc(r.note)} ${basisBadge(r.figure_basis)}</td>
      </tr>`).join(''));
  }

  function renderOperators(rows) {
    if (!rows || !rows.length) { fillBody('ltcres-operators-table', emptyRow(9, 'No rows.')); return; }
    fillBody('ltcres-operators-table', rows.map((r) => `
      <tr>
        <td><strong>${esc(r.player)}</strong><br><span style="color:var(--text-light);">${esc(r.ownership)}</span></td>
        <td>${esc(r.country)}</td>
        <td>${esc(r.segment)}</td>
        <td>${r.revenue_bn == null ? '—' : `${esc(r.currency)} ${num(r.revenue_bn, 2)}bn`} <span style="color:var(--text-light);">FY${esc(r.fiscal_year)}</span></td>
        <td>${r.margin_pct == null ? '—' : `${num(r.margin_pct, 1)}${String(r.margin_metric || '').includes('×') ? '×' : '%'}`}<br><span style="color:var(--text-light);">${esc(r.margin_metric || '')}</span></td>
        <td>${r.beds_or_units == null ? '—' : Number(r.beds_or_units).toLocaleString('en-US')} ${esc(r.unit_label || '')}</td>
        <td>${r.occupancy_pct == null ? '—' : pct(r.occupancy_pct, 1)}</td>
        <td>${basisBadge(r.figure_basis)}</td>
        <td style="color:var(--text-light);">${esc(r.note)}</td>
      </tr>`).join(''));
  }

  function renderMargins(rows) {
    if (!rows || !rows.length) { fillBody('ltcres-margins-table', emptyRow(6, 'No rows.')); return; }
    fillBody('ltcres-margins-table', rows.map((r) => `
      <tr>
        <td><strong>${esc(r.segment)}</strong></td>
        <td>${esc(r.metric)}</td>
        <td>${pct(r.low_pct, 1)} – <strong>${pct(r.mid_pct, 1)}</strong> – ${pct(r.high_pct, 1)}</td>
        <td>${esc(r.year)}</td>
        <td>${basisBadge(r.figure_basis)}</td>
        <td style="color:var(--text-light);">${esc(r.note)}</td>
      </tr>`).join(''));
  }

  function renderWorkforce(rows) {
    if (!rows || !rows.length) { fillBody('ltcres-workforce-table', emptyRow(5, 'No rows.')); return; }
    fillBody('ltcres-workforce-table', rows.map((r) => `
      <tr>
        <td>${esc(String(r.region).toUpperCase())}</td>
        <td><strong>${esc(r.metric)}</strong></td>
        <td>${Number(r.value).toLocaleString('en-US', { maximumFractionDigits: 2 })} ${esc(r.unit)} <span style="color:var(--text-light);">(${esc(r.year)})</span></td>
        <td>${basisBadge(r.figure_basis)}</td>
        <td style="color:var(--text-light);">${esc(r.note)}</td>
      </tr>`).join(''));
  }

  function renderRegulation(rows) {
    if (!rows || !rows.length) { fillBody('ltcres-regulation-table', emptyRow(7, 'No rows.')); return; }
    fillBody('ltcres-regulation-table', rows.map((r) => `
      <tr>
        <td><strong>${esc(r.jurisdiction)}</strong></td>
        <td>${esc(r.financing_model)}<br><span style="color:var(--text-light);">${esc(r.founding_statute)}</span></td>
        <td>${esc(r.key_reform)}</td>
        <td>${esc(r.staffing_standard)}</td>
        <td>${esc(r.quality_regime)}</td>
        <td>${esc(r.accommodation_standard)}</td>
        <td style="color:var(--text-light);">${esc(r.direction)}</td>
      </tr>`).join(''));
  }

  function renderCostOfCare(rows) {
    if (!rows || !rows.length) { fillBody('ltcres-cost-table', emptyRow(7, 'No rows.')); return; }
    const years = Array.from(new Set(rows.map((r) => r.year))).sort();
    const settings = ['home_health_aide', 'adult_day', 'assisted_living', 'nursing_semi_private', 'nursing_private'];
    const labels = {};
    rows.forEach((r) => { labels[r.setting] = r.setting_label; });
    const byKey = {};
    rows.forEach((r) => { byKey[`${r.setting}:${r.year}`] = r; });
    const head = document.querySelector('#ltcres-cost-table thead tr');
    if (head) head.innerHTML = `<th>Setting</th>${years.map((y) => `<th>${y}</th>`).join('')}<th>CAGR</th>`;
    fillBody('ltcres-cost-table', settings.map((s) => {
      const last = years.map((y) => byKey[`${s}:${y}`]).filter(Boolean).pop();
      return `<tr><td><strong>${esc(labels[s] || s)}</strong></td>${years.map((y) => {
        const r = byKey[`${s}:${y}`];
        return `<td>${r ? money(r.annual_cost_usd) : '—'}</td>`;
      }).join('')}<td>${last && last.cagr_since_first_survey_pct != null ? pct(last.cagr_since_first_survey_pct, 2) : '—'}</td></tr>`;
    }).join(''));
  }

  function renderForecastTable(rows) {
    if (!rows || !rows.length) { fillBody('ltcres-forecast-table', emptyRow(10, 'No rows.')); return; }
    const sampled = rows.filter((r, i) => r.year % 5 === 0 || i === rows.length - 1);
    fillBody('ltcres-forecast-table', sampled.map((r) => `
      <tr>
        <td>${r.year}</td>
        <td>${esc(r.era)}</td>
        <td>${pct(r.pop80_share_pct, 1)}</td>
        <td>${num(r.recipients_index, 0)}</td>
        <td>${pct(r.home_share_pct, 0)}</td>
        <td>${num(r.residential_demand_index, 0)}</td>
        <td>${num(r.home_demand_index, 0)}</td>
        <td>${pct(r.ltc_spend_gdp_pct, 2)}</td>
        <td>${bn(r.ltc_spend_usd_bn, 0)} <span style="color:var(--text-light);">(${bn(r.ltc_spend_at_2025_gdp_usd_bn, 0)} at 2025 GDP)</span></td>
        <td>${pct(r.public_share_pct, 0)}</td>
      </tr>`).join(''));
  }

  function renderTam(rows) {
    if (!rows || !rows.length) { fillBody('ltcres-tam-table', emptyRow(6, 'No rows.')); return; }
    fillBody('ltcres-tam-table', rows.map((r) => `
      <tr${r.segment === 'total' ? ' style="font-weight:600;"' : ''}>
        <td>${r.year}</td>
        <td>${esc(r.segment.replace('_', ' '))}</td>
        <td>${bn(r.tam_usd_bn, 1)}</td>
        <td>${bn(r.tam_at_2025_gdp_usd_bn, 1)}</td>
        <td>${bn(r.sam_usd_bn, 1)}</td>
        <td>${bn(r.som_usd_bn, 2)}</td>
      </tr>`).join(''));
  }

  function renderScenarios(rows) {
    if (!rows || !rows.length) { fillBody('ltcres-scenarios-table', emptyRow(8, 'No rows.')); return; }
    fillBody('ltcres-scenarios-table', rows.map((r) => `
      <tr${r.selected ? ' style="background:rgba(201,160,78,0.12);font-weight:600;"' : ''}>
        <td>${esc(r.label)}${r.selected ? ' <span class="header-badge" style="font-size:10px;">selected</span>' : ''}</td>
        <td>${pct(r.home_share_target_pct, 0)}</td>
        <td>${num(r.recipients_index_2050, 0)} / ${num(r.residential_demand_index_2050, 0)}</td>
        <td>${pct(r.ltc_spend_gdp_pct_2050, 2)}</td>
        <td>${num(r.recipients_index_end, 0)} / ${num(r.residential_demand_index_end, 0)}</td>
        <td>${pct(r.ltc_spend_gdp_pct_end, 2)}</td>
        <td>${bn(r.ltc_spend_usd_bn_end, 0)}</td>
        <td style="color:var(--text-light);font-weight:400;">${esc(r.note)}</td>
      </tr>`).join(''));
  }

  function renderHedge(book, allocation, summary) {
    if (!book || !book.length) {
      fillBody('ltcres-hedge-book-table', emptyRow(8, 'No age bands in range.'));
    } else {
      fillBody('ltcres-hedge-book-table', book.map((r) => `
        <tr>
          <td>${r.age_min}–${r.age_max}</td>
          <td>${Number(r.band_lives).toLocaleString('en-US')}</td>
          <td>${num(r.incidence_per_1000, 3)}</td>
          <td>${num(r.mean_claim_duration_years, 2)}y</td>
          <td>${pct(r.steady_state_prevalence_pct, 3)}</td>
          <td>${money(r.expected_annual_claims)}</td>
          <td>${money(r.stressed_annual_claims)}</td>
          <td>${money(r.expected_new_claim_cost)}</td>
        </tr>`).join(''));
    }
    if (!allocation || !allocation.length) {
      fillBody('ltcres-hedge-alloc-table', emptyRow(8, 'No allocation.'));
    } else {
      fillBody('ltcres-hedge-alloc-table', allocation.map((r) => `
        <tr>
          <td><strong>${esc(r.label)}</strong><br><span style="color:var(--text-light);">${esc(r.rationale)}</span></td>
          <td>${pct(r.allocation_pct, 0)}</td>
          <td>${money(r.capital)}</td>
          <td>${pct(r.yield_pct, 1)}</td>
          <td>${num(r.claim_beta, 2)}</td>
          <td>${money(r.expected_income)}</td>
          <td>${money(r.stressed_income)} <span style="color:var(--text-light);">(+${money(r.income_uplift_under_stress)})</span></td>
          <td>${esc(r.liquidity)} · ${esc(r.volatility)}</td>
        </tr>`).join(''));
    }
    const s = summary || {};
    const el = document.getElementById('ltcres-hedge-summary');
    if (el) {
      el.textContent = `Book of ${Number(s.book_lives || 0).toLocaleString('en-US')} lives — expected claims ${money(s.expected_annual_claims)} a year `
        + `(stressed ${money(s.stressed_annual_claims)}); hedge capital ${money(s.hedge_capital)} yields ${money(s.hedge_income)} `
        + `(${pct(s.hedge_ratio_pct, 1)} of claims, weighted yield ${pct(s.weighted_yield_pct, 2)}, β ${num(s.weighted_claim_beta, 2)}); `
        + `under +${num(s.incidence_stress_pct, 0)}% incidence the income uplift ${money(s.income_delta_under_stress)} offsets `
        + `${pct(s.stress_offset_pct, 1)} of the extra ${money(s.claims_delta_under_stress)} claims. `
        + `10-year PV: claims ${money(s.pv_10y_claims)} vs hedge income ${money(s.pv_10y_hedge_income)}.`;
    }
  }

  function renderSwot(rows) {
    const el = document.getElementById('ltcres-swot');
    if (!el) return;
    const quadrants = [
      ['strength', 'Strengths', '#2f855a'],
      ['weakness', 'Weaknesses', '#c53030'],
      ['opportunity', 'Opportunities', '#2b6cb0'],
      ['threat', 'Threats', '#b7791f'],
    ];
    el.innerHTML = quadrants.map(([key, label, color]) => {
      const items = (rows || []).filter((r) => r.quadrant === key);
      return `<div class="ltcres-swot-cell" style="border-top:4px solid ${color};">
        <div class="ltcres-swot-title" style="color:${color};">${label}</div>
        <ul>${items.map((r) => `<li><span class="ltcres-weight" title="weight ${r.weight}/5">${'●'.repeat(r.weight)}${'○'.repeat(5 - r.weight)}</span> ${esc(r.item)}<br><span style="color:var(--text-light);font-size:11px;">${esc(r.applies_to)} · ${esc((r.source_ids || []).join(', '))}</span></li>`).join('')}</ul>
      </div>`;
    }).join('');
  }

  function renderCaseStudies(rows) {
    const el = document.getElementById('ltcres-cases');
    if (!el) return;
    el.innerHTML = (rows || []).map((r) => `
      <div class="ltcres-case">
        <div class="ltcres-case-title">${esc(r.title)} <span class="header-badge" style="font-size:10px;">${esc(r.segment)}</span></div>
        <div style="color:var(--text-light);font-size:12px;margin-bottom:6px;">${esc(r.jurisdiction)} · ${esc(r.period)} · ${esc(r.metric)}</div>
        <p style="margin-bottom:6px;">${esc(r.what_happened)}</p>
        <p style="margin:0;"><strong>Lesson:</strong> ${esc(r.lesson)}</p>
        <div style="color:var(--text-light);font-size:11px;margin-top:6px;">sources: ${esc((r.source_ids || []).join(', '))}</div>
      </div>`).join('');
  }

  function renderPayerMix(rows) {
    if (!rows || !rows.length) { fillBody('ltcres-payer-table', emptyRow(9, 'No rows.')); return; }
    fillBody('ltcres-payer-table', rows.map((r) => `
      <tr>
        <td>${esc(String(r.region).toUpperCase())} · ${esc(r.segment.replace(/_/g, ' '))}</td>
        <td>${r.year}</td>
        <td>${pct(r.public_pct, 1)}</td>
        <td>${r.medicare_pct == null ? '—' : pct(r.medicare_pct, 1)}</td>
        <td>${r.medicaid_pct == null ? '—' : pct(r.medicaid_pct, 1)}</td>
        <td>${r.private_insurance_pct == null ? '—' : pct(r.private_insurance_pct, 1)}</td>
        <td>${r.out_of_pocket_pct == null ? '—' : pct(r.out_of_pocket_pct, 1)}</td>
        <td>${r.other_pct == null ? '—' : pct(r.other_pct, 1)}</td>
        <td>${basisBadge(r.figure_basis)} <span style="color:var(--text-light);">${esc(r.note)}</span></td>
      </tr>`).join(''));
  }

  // ---------------------------------------------------------------- charts
  function destroyChart(name) {
    const chart = charts[name];
    if (chart && typeof chart.destroy === 'function') {
      try { chart.destroy(); } catch (err) { /* ignore */ }
    }
    charts[name] = null;
  }

  function makeChart(name, canvasId, config) {
    destroyChart(name);
    const canvas = document.getElementById(canvasId);
    if (!canvas || typeof Chart === 'undefined') return;
    charts[name] = new Chart(canvas, config);
  }

  const NAVY = '#0e2f63';
  const GOLD = '#c9a04e';
  const CYAN = '#4fd8ff';
  const GREEN = '#38a169';
  const RED = '#e53e3e';
  const PURPLE = '#805ad5';

  function renderCharts(pack) {
    const t = pack.tables || {};
    const spending = t.spending_history || [];
    makeChart('spending', 'ltcres-spending-chart', {
      type: 'line',
      data: {
        labels: spending.map((r) => r.year),
        datasets: [
          { label: 'Nursing care $bn', data: spending.map((r) => r.nursing_care_bn), borderColor: NAVY, backgroundColor: 'rgba(14,47,99,0.15)', fill: true, tension: 0.25, pointRadius: 2 },
          { label: 'Home health $bn', data: spending.map((r) => r.home_health_bn), borderColor: GOLD, backgroundColor: 'rgba(201,160,78,0.2)', fill: true, tension: 0.25, pointRadius: 2 },
          { label: 'Home health share %', data: spending.map((r) => r.home_health_share_pct), borderColor: GREEN, borderDash: [6, 4], tension: 0.25, pointRadius: 0, yAxisID: 'y1' },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
        scales: {
          y: { title: { display: true, text: 'US spend, $bn (CMS NHE)' } },
          y1: { position: 'right', min: 0, max: 100, title: { display: true, text: 'Home health share %' }, grid: { drawOnChartArea: false } },
        },
      },
    });

    const cost = t.cost_of_care || [];
    const years = Array.from(new Set(cost.map((r) => r.year))).sort();
    const series = [
      ['nursing_private', 'Nursing private room', RED],
      ['nursing_semi_private', 'Nursing semi-private', NAVY],
      ['home_health_aide', 'Home health aide (44 h/wk)', CYAN],
      ['assisted_living', 'Assisted living', GOLD],
      ['adult_day', 'Adult day care', GREEN],
    ];
    makeChart('cost', 'ltcres-cost-chart', {
      type: 'line',
      data: {
        labels: years,
        datasets: series.map(([key, label, color]) => ({
          label, borderColor: color, tension: 0.2, pointRadius: 3, spanGaps: true,
          data: years.map((y) => { const r = cost.find((c) => c.setting === key && c.year === y); return r ? r.annual_cost_usd : null; }),
        })),
      },
      options: { responsive: true, maintainAspectRatio: false, scales: { y: { title: { display: true, text: 'Annual median cost, USD' } } } },
    });

    const fc = t.demand_forecast || [];
    makeChart('forecast', 'ltcres-forecast-chart', {
      type: 'line',
      data: {
        labels: fc.map((r) => r.year),
        datasets: [
          { label: 'Recipients index', data: fc.map((r) => r.recipients_index), borderColor: NAVY, tension: 0.2, pointRadius: 0, borderWidth: 2 },
          { label: 'Residential demand index', data: fc.map((r) => r.residential_demand_index), borderColor: GOLD, tension: 0.2, pointRadius: 0, borderWidth: 2 },
          { label: 'Home demand index', data: fc.map((r) => r.home_demand_index), borderColor: CYAN, tension: 0.2, pointRadius: 0, borderWidth: 2 },
          { label: 'LTC spend % GDP', data: fc.map((r) => r.ltc_spend_gdp_pct), borderColor: GREEN, borderDash: [6, 4], tension: 0.2, pointRadius: 0, yAxisID: 'y1' },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
        scales: {
          y: { title: { display: true, text: 'Index (2025 = 100)' } },
          y1: { position: 'right', title: { display: true, text: 'LTC spend % GDP' }, grid: { drawOnChartArea: false } },
        },
      },
    });

    const tam = (t.tam_sam_som || []);
    const tamYears = Array.from(new Set(tam.map((r) => r.year)));
    const pick = (seg, key) => tamYears.map((y) => { const r = tam.find((x) => x.year === y && x.segment === seg); return r ? r[key] : null; });
    makeChart('tam', 'ltcres-tam-chart', {
      type: 'bar',
      data: {
        labels: tamYears,
        datasets: [
          { label: 'Residential TAM', data: pick('residential', 'tam_usd_bn'), backgroundColor: 'rgba(14,47,99,0.85)', stack: 'tam' },
          { label: 'Home-care TAM', data: pick('home_care', 'tam_usd_bn'), backgroundColor: 'rgba(79,216,255,0.75)', stack: 'tam' },
          { label: 'SAM (private providers)', data: pick('total', 'sam_usd_bn'), backgroundColor: 'rgba(201,160,78,0.85)', stack: 'sam' },
          { label: 'SOM', data: pick('total', 'som_usd_bn'), backgroundColor: 'rgba(56,161,105,0.9)', stack: 'som' },
        ],
      },
      options: { responsive: true, maintainAspectRatio: false, scales: { x: { stacked: true }, y: { stacked: true, title: { display: true, text: '$bn nominal' } } } },
    });

    const scen = t.scenarios || [];
    makeChart('scenarios', 'ltcres-scenarios-chart', {
      type: 'bar',
      data: {
        labels: scen.map((r) => r.scenario.replace(/_/g, ' ')),
        datasets: [
          { label: 'Residential demand index (end)', data: scen.map((r) => r.residential_demand_index_end), backgroundColor: 'rgba(201,160,78,0.85)' },
          { label: 'Recipients index (end)', data: scen.map((r) => r.recipients_index_end), backgroundColor: 'rgba(14,47,99,0.85)' },
          { label: 'LTC % GDP (end) ×50', data: scen.map((r) => r.ltc_spend_gdp_pct_end * 50), backgroundColor: 'rgba(56,161,105,0.7)' },
        ],
      },
      options: { responsive: true, maintainAspectRatio: false, scales: { y: { title: { display: true, text: 'Index (2025 = 100)' } } } },
    });

    const payer = (t.payer_mix || []).filter((r) => r.shares_complete || r.medicare_pct == null);
    makeChart('payer', 'ltcres-payer-chart', {
      type: 'bar',
      data: {
        labels: payer.map((r) => `${String(r.region).toUpperCase()} ${r.segment.replace(/_/g, ' ')} ${r.year}`),
        datasets: [
          { label: 'Medicaid / public budget', data: payer.map((r) => r.medicaid_pct != null ? r.medicaid_pct : r.public_pct), backgroundColor: 'rgba(14,79,138,0.9)', stack: 'p' },
          { label: 'Medicare / social insurance', data: payer.map((r) => r.medicare_pct != null ? r.medicare_pct : 0), backgroundColor: 'rgba(43,108,176,0.9)', stack: 'p' },
          { label: 'Other public', data: payer.map((r) => r.medicare_pct != null ? Math.max(0, r.public_pct - r.medicare_pct - r.medicaid_pct) : 0), backgroundColor: 'rgba(79,216,255,0.9)', stack: 'p' },
          { label: 'Private insurance', data: payer.map((r) => r.private_insurance_pct || 0), backgroundColor: 'rgba(201,160,78,0.9)', stack: 'p' },
          { label: 'Out of pocket', data: payer.map((r) => r.out_of_pocket_pct || 0), backgroundColor: 'rgba(227,191,111,0.9)', stack: 'p' },
          { label: 'Other', data: payer.map((r) => r.other_pct || 0), backgroundColor: 'rgba(74,85,104,0.9)', stack: 'p' },
        ],
      },
      options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, scales: { x: { stacked: true, max: 100, title: { display: true, text: '% of spend' } }, y: { stacked: true } } },
    });

    const alloc = t.hedge_allocation || [];
    makeChart('alloc', 'ltcres-alloc-chart', {
      type: 'doughnut',
      data: {
        labels: alloc.map((r) => r.label),
        datasets: [{ data: alloc.map((r) => r.allocation_pct), backgroundColor: [NAVY, GOLD, CYAN, '#a0aec0'] }],
      },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'right' } } },
    });

    const margins = t.margin_benchmarks || [];
    makeChart('margins', 'ltcres-margins-chart', {
      type: 'bar',
      data: {
        labels: margins.map((r) => r.segment),
        datasets: [
          { label: 'Low–high range', data: margins.map((r) => [r.low_pct, r.high_pct]), backgroundColor: 'rgba(14,47,99,0.35)', borderColor: NAVY, borderWidth: 1 },
          { label: 'Mid', data: margins.map((r) => r.mid_pct), type: 'scatter', backgroundColor: GOLD, pointRadius: 5, pointStyle: 'rectRot' },
        ],
      },
      options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, scales: { x: { title: { display: true, text: '% (margin or cap rate)' } } } },
    });

    const ops = (t.operators || []).filter((r) => r.margin_pct != null && !String(r.margin_metric || '').includes('×'));
    makeChart('ops', 'ltcres-operators-chart', {
      type: 'bar',
      data: {
        labels: ops.map((r) => r.player),
        datasets: [{ label: `${'Reported margin %'} (metric varies — see table)`, data: ops.map((r) => r.margin_pct), backgroundColor: ops.map((r) => r.figure_basis === 'published' ? 'rgba(14,47,99,0.9)' : 'rgba(201,160,78,0.8)') }],
      },
      options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: true } }, scales: { x: { title: { display: true, text: 'Navy = published filing · gold = estimate' } } } },
    });
  }

  // ---------------------------------------------------------------- media
  function renderMedia(pack) {
    const media = pack.media || {};
    const gallery = document.getElementById('ltcres-gallery');
    if (gallery) {
      gallery.innerHTML = (media.illustrations || []).map((item) => `
        <figure class="ltcres-figure">
          <img src="${esc(item.url)}" alt="${esc(item.title)}" loading="lazy">
          <figcaption><strong>${esc(item.title)}</strong><br><span style="color:var(--text-light);">${esc(item.caption)}</span></figcaption>
        </figure>`).join('');
    }
    const lib = document.getElementById('ltcres-library');
    if (lib) {
      const items = media.library || [];
      if (!items.length) {
        lib.innerHTML = '<p style="color:var(--text-light);margin:0;">No long-term-care photos or videos in the PHINS media library yet. Upload an asset whose name or source mentions long-term care, nursing home, home care, assisted living or סיעוד and it appears here automatically (same-origin playback only).</p>';
      } else {
        lib.innerHTML = items.map((item) => item.kind === 'video'
          ? `<figure class="ltcres-figure"><video controls preload="metadata" src="${esc(item.url)}"${item.thumbnail ? ` poster="${esc(item.thumbnail)}"` : ''}></video><figcaption><strong>${esc(item.title)}</strong><br><span style="color:var(--text-light);">${esc(item.source || '')} ${esc(item.uploaded_at || '')}</span></figcaption></figure>`
          : `<figure class="ltcres-figure"><img src="${esc(item.url)}" alt="${esc(item.title)}" loading="lazy"><figcaption><strong>${esc(item.title)}</strong><br><span style="color:var(--text-light);">${esc(item.source || '')}</span></figcaption></figure>`).join('');
      }
    }
    const pubs = document.getElementById('ltcres-publications');
    if (pubs) {
      pubs.innerHTML = (media.external_publications || []).map((p) => `<li><a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.title)}</a> <span style="color:var(--text-light);">· ${esc(p.kind)}</span></li>`).join('');
    }
    const note = document.getElementById('ltcres-media-note');
    if (note) note.textContent = media.note || '';
    resetPlayer();
    drawFrame(0);
  }

  // ---------------------------------------------------------------- timeline player
  function frames() {
    return ((lastPack || {}).media || {}).timeline_player || [];
  }

  function stopPlayer() {
    if (player.timer) { clearInterval(player.timer); player.timer = null; }
    player.playing = false;
    const btn = document.getElementById('ltcres-play');
    if (btn) btn.textContent = 'Play briefing';
  }

  function resetPlayer() {
    stopPlayer();
    player.frame = 0;
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function drawFrame(index) {
    const canvas = document.getElementById('ltcres-player');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.width;
    const H = canvas.height;
    const list = frames();
    const grad = ctx.createLinearGradient(0, 0, W, H);
    grad.addColorStop(0, '#060d1f');
    grad.addColorStop(1, '#0e2f63');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, W, H);

    ctx.fillStyle = '#f7fafc';
    ctx.font = '700 28px "Space Grotesk", Inter, Arial, sans-serif';
    ctx.fillText('PHINS', 40, 52);
    ctx.font = '500 15px Inter, Arial, sans-serif';
    ctx.fillStyle = '#c9d4ea';
    ctx.fillText('Research & Audit · Long-term care residential services — fifty years back, fifty years forward', 130, 52);
    if (!list.length) {
      ctx.fillStyle = '#9fb3d9';
      ctx.font = '500 16px Inter, Arial, sans-serif';
      ctx.fillText('Recalculate the study to load the briefing timeline.', 40, 120);
      return;
    }
    const i = Math.max(0, Math.min(list.length - 1, index));
    const frame = list[i];
    const hist = list.filter((f) => f.phase === 'history');
    const fcst = list.filter((f) => f.phase === 'forecast');
    const histMax = Math.max(1, ...hist.map((f) => Number(f.value || 0)));
    const fcstMax = Math.max(1, ...fcst.map((f) => Number(f.value || 0)));

    // Bars across the bottom; history navy→cyan, forecast gold.
    const left = 40;
    const right = W - 40;
    const baseY = H - 70;
    const slot = (right - left) / list.length;
    list.forEach((f, j) => {
      const isHist = f.phase === 'history';
      const scale = isHist ? histMax : fcstMax;
      const h = Math.max(4, (Number(f.value || 0) / scale) * 150);
      const x = left + j * slot;
      ctx.fillStyle = j > i ? 'rgba(159,179,217,0.18)' : (isHist ? (j === i ? '#4fd8ff' : 'rgba(79,216,255,0.6)') : (j === i ? '#e3bf6f' : 'rgba(201,160,78,0.7)'));
      roundRect(ctx, x + 3, baseY - h, Math.max(6, slot - 6), h, 3);
      ctx.fill();
      ctx.fillStyle = j === i ? '#f7fafc' : '#9fb3d9';
      ctx.font = `${j === i ? '700' : '400'} 11px Inter, Arial, sans-serif`;
      ctx.textAlign = 'center';
      ctx.fillText(String(f.year), x + slot / 2, baseY + 18);
      ctx.textAlign = 'left';
    });
    // divider between history and forecast
    if (hist.length && fcst.length) {
      const dx = left + hist.length * slot;
      ctx.strokeStyle = 'rgba(247,250,252,0.35)';
      ctx.setLineDash([6, 6]);
      ctx.beginPath(); ctx.moveTo(dx, 110); ctx.lineTo(dx, baseY + 4); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#9fb3d9';
      ctx.font = '500 11px Inter, Arial, sans-serif';
      ctx.fillText('history (CMS NHE) ◀', dx - 118, 108);
      ctx.fillText('▶ projection', dx + 6, 108);
    }

    // Headline card
    const cardY = 120;
    ctx.fillStyle = 'rgba(11,26,58,0.92)';
    roundRect(ctx, 40, cardY, W - 80, 118, 14);
    ctx.fill();
    ctx.strokeStyle = frame.phase === 'history' ? '#4fd8ff' : '#e3bf6f';
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.fillStyle = frame.phase === 'history' ? '#4fd8ff' : '#e3bf6f';
    ctx.font = '700 40px "Space Grotesk", Inter, Arial, sans-serif';
    ctx.fillText(String(frame.year), 60, cardY + 52);
    ctx.fillStyle = '#f7fafc';
    ctx.font = '600 18px Inter, Arial, sans-serif';
    ctx.fillText(String(frame.headline || ''), 170, cardY + 40);
    ctx.fillStyle = '#c9d4ea';
    ctx.font = '400 13px Inter, Arial, sans-serif';
    ctx.fillText(String(frame.value_label || ''), 170, cardY + 64);
    ctx.fillStyle = '#9fb3d9';
    const theme = String(frame.theme || '');
    ctx.fillText(theme.length > 120 ? `${theme.slice(0, 117)}…` : theme, 170, cardY + 88);
    ctx.fillStyle = '#9fb3d9';
    ctx.font = '500 12px Inter, Arial, sans-serif';
    ctx.fillText(`${String(frame.era || '').replace(/_/g, ' ')} · frame ${i + 1} / ${list.length}`, 60, cardY + 104);

    ctx.fillStyle = '#9fb3d9';
    ctx.font = '400 11px Inter, Arial, sans-serif';
    ctx.fillText('Rendered in the browser from the study pack · PHINS confidential actuarial research', 40, H - 18);
    setText('ltcres-player-caption', `${frame.year} — ${frame.headline}`);
  }

  function play() {
    const list = frames();
    if (!list.length) { setStatus('Load the study before playing the briefing.', true); return; }
    if (player.playing) { stopPlayer(); drawFrame(player.frame); return; }
    player.playing = true;
    const btn = document.getElementById('ltcres-play');
    if (btn) btn.textContent = 'Pause';
    if (player.frame >= list.length - 1) player.frame = 0;
    drawFrame(player.frame);
    player.timer = setInterval(() => {
      player.frame += 1;
      if (player.frame >= list.length) {
        player.frame = list.length - 1;
        stopPlayer();
        drawFrame(player.frame);
        if (player.recorder && player.recorder.state === 'recording') {
          setTimeout(() => { try { player.recorder.stop(); } catch (err) { /* ignore */ } }, 400);
        }
        return;
      }
      drawFrame(player.frame);
    }, 1400);
  }

  function record() {
    const canvas = document.getElementById('ltcres-player');
    if (!canvas || typeof canvas.captureStream !== 'function' || typeof MediaRecorder === 'undefined') {
      setStatus('This browser cannot record the canvas to a video file. Use Play to view the briefing.', true);
      return;
    }
    if (!frames().length) { setStatus('Load the study before recording the briefing.', true); return; }
    resetPlayer();
    player.chunks = [];
    const stream = canvas.captureStream(30);
    const mime = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'].find((m) => MediaRecorder.isTypeSupported(m)) || '';
    const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    recorder.ondataavailable = (ev) => { if (ev.data && ev.data.size) player.chunks.push(ev.data); };
    recorder.onstop = () => {
      const blob = new Blob(player.chunks, { type: mime || 'video/webm' });
      const url = URL.createObjectURL(blob);
      const video = document.getElementById('ltcres-recorded');
      const link = document.getElementById('ltcres-recorded-link');
      if (video) { video.src = url; video.style.display = 'block'; }
      if (link) { link.href = url; link.download = `phins-ltc-residential-briefing-${(lastPack || {}).params ? lastPack.params.region : 'study'}.webm`; link.style.display = 'inline-flex'; }
      setStatus(`Briefing video recorded (${(blob.size / 1024).toFixed(0)} KB, ${mime || 'video/webm'}).`);
      player.recorder = null;
    };
    player.recorder = recorder;
    recorder.start(250);
    setStatus('Recording the briefing video…');
    play();
  }

  function step(delta) {
    const list = frames();
    if (!list.length) return;
    stopPlayer();
    player.frame = Math.max(0, Math.min(list.length - 1, player.frame + delta));
    drawFrame(player.frame);
  }

  // ---------------------------------------------------------------- integrity
  function renderIntegrity(pack) {
    const el = document.getElementById('ltcres-integrity');
    if (!el) return;
    const integ = pack.integrity || {};
    const hash = integ.pack_hash || integ.tables_hash || '';
    const shortHash = hash ? `${hash.slice(0, 12)}…` : '—';
    const checks = [
      ['TAM ≥ SAM ≥ SOM', integ.tam_sam_som_monotone],
      ['segments reconcile', integ.tam_segments_reconcile && integ.forecast_spend_segments_reconcile],
      ['payer shares = 100%', integ.payer_shares_sum_to_100],
      ['setting mix = 100%', integ.setting_mix_sums_to_100],
      ['hedge allocation = 100%', integ.hedge_allocation_sums_to_100],
      ['book lives match', integ.hedge_book_lives_match],
      ['NHE totals match', integ.spending_history_totals_match],
      ['source ids resolve', integ.source_ids_resolve],
    ];
    const rows = Object.keys(integ.row_counts || {}).map((k) => `${k} ${integ.row_counts[k]}`).join(' · ');
    el.innerHTML = `<strong>Integrity ${esc(shortHash)}</strong> · ${integ.all_checks_pass ? '<span style="color:#2f855a;">all checks pass</span>' : '<span style="color:var(--danger);">CHECK FAILURE</span>'} — `
      + checks.map(([label, ok]) => `<span style="color:${ok ? '#2f855a' : 'var(--danger)'};">${ok ? '✓' : '✗'} ${esc(label)}</span>`).join(' · ')
      + `<br><span style="color:var(--text-light);">params ${esc((integ.params_hash || '').slice(0, 12))}… · tables ${esc((integ.tables_hash || '').slice(0, 12))}… · ${(integ.sources_used || []).length} sources used · figure bases: ${esc((integ.figure_basis_values || []).join(', '))}<br>rows: ${esc(rows)}</span>`;
  }

  // ---------------------------------------------------------------- orchestration
  function render(pack) {
    lastPack = pack;
    const t = pack.tables || {};
    renderKpis(pack);
    renderNarrative(pack);
    renderSources(pack);
    renderMarketStructure(t.market_structure);
    renderSettingComparison(t.setting_comparison);
    renderPayerMix(t.payer_mix);
    renderCostOfCare(t.cost_of_care);
    renderOperators(t.operators);
    renderMargins(t.margin_benchmarks);
    renderWorkforce(t.workforce);
    renderRegulation(t.regulation);
    renderForecastTable(t.demand_forecast);
    renderTam(t.tam_sam_som);
    renderScenarios(t.scenarios);
    renderHedge(t.hedge_book, t.hedge_allocation, pack.hedge_summary);
    renderSwot(t.swot);
    renderCaseStudies(t.case_studies);
    renderCharts(pack);
    renderMedia(pack);
    renderIntegrity(pack);
    setStatus(`Study ${pack.study_id} · ${pack.region_label} · ${pack.scenario_label} · ${(pack.integrity || {}).all_checks_pass ? 'integrity checks pass' : 'integrity FAILURE'}.`);
  }

  async function load() {
    const section = document.getElementById('section-ltc-residential-research');
    if (!section) return lastPack;
    setStatus('Calculating the 1975–2075 study…');
    const requestId = Symbol('ltcres-load');
    inflight = requestId;
    try {
      const res = await fetch(`/api/actuarial/ltc-residential-research?${queryString()}`, { headers: authHeaders() });
      const data = await res.json();
      if (inflight !== requestId) return lastPack;
      if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
      render(data);
      return data;
    } catch (err) {
      if (inflight === requestId) setStatus(`Failed: ${err.message}`, true);
      return null;
    }
  }

  function reset() {
    Object.keys(DEFAULTS).forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.value = DEFAULTS[id];
    });
    return load();
  }

  async function downloadBlob(url, filename, okMessage) {
    try {
      const res = await fetch(url, { headers: authHeaders() });
      if (!res.ok) {
        let message = `HTTP ${res.status}`;
        try { const body = await res.json(); message = body.error || message; } catch (err) { /* ignore */ }
        throw new Error(message);
      }
      const blob = await res.blob();
      const href = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = href;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(href);
      setStatus(okMessage);
    } catch (err) {
      setStatus(`Download failed: ${err.message}`, true);
    }
  }

  function download(fmt) {
    const table = document.getElementById('ltcres-download-table')?.value || 'demand_forecast';
    const format = fmt === 'json' ? 'json' : 'csv';
    return downloadBlob(
      `/api/actuarial/ltc-residential-research/download?${queryString({ table, format })}`,
      `phins-ltc-residential-${table}.${format}`,
      `Downloaded ${table} as ${format}.`,
    );
  }

  function downloadPdf() {
    return downloadBlob(
      `/api/actuarial/ltc-residential-research/download?${queryString({ format: 'pdf' })}`,
      'phins-ltc-residential-market-strategy.pdf',
      'Downloaded the full study PDF.',
    );
  }

  root.PhinsLtcResidentialResearch = {
    load,
    reset,
    download,
    downloadPdf,
    play,
    record,
    step,
    collectParams,
    lastPack() { return lastPack; },
  };
})(typeof window !== 'undefined' ? window : globalThis);
