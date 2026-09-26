/**
 * Actuary dashboard — LTC 3+ADL / life reinsurance research (Research & Audit).
 *
 * Reads the adjustable sliders, calls /api/actuarial/ltc-life-research, and
 * fills the tables, KPIs, and Chart.js canvases. Downloads and promote /
 * stage reuse the same slider set so the file an actuary saves matches the
 * screen they are looking at.
 */
(function (root) {
  let lastPack = null;
  let historyChart = null;
  let forecastChart = null;
  let inflight = null;

  function authHeaders() {
    const headers = {};
    if (typeof token === 'string' && token) {
      headers.Authorization = `Bearer ${token}`;
    }
    return headers;
  }

  function money(value) {
    if (typeof fmtCurrency === 'function') return fmtCurrency(value);
    const n = Number(value || 0);
    return (n < 0 ? '-$' : '$') + Math.abs(n).toLocaleString('en-US', {
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    });
  }

  function pct(value, digits) {
    const d = digits == null ? 1 : digits;
    return `${Number(value || 0).toFixed(d)}%`;
  }

  function num(value, digits) {
    const d = digits == null ? 2 : digits;
    return Number(value || 0).toLocaleString('en-US', {
      minimumFractionDigits: d,
      maximumFractionDigits: d,
    });
  }

  function band(row) {
    return `${row.age_min}–${row.age_max}`;
  }

  function setStatus(message, isError) {
    const el = document.getElementById('ltc-research-status');
    if (!el) return;
    el.textContent = message || '';
    el.style.color = isError ? 'var(--danger)' : 'var(--text-light)';
  }

  function collectParams() {
    return {
      year_from: document.getElementById('ltc-year-from')?.value || '1975',
      year_to: document.getElementById('ltc-year-to')?.value || '2025',
      forecast_end: document.getElementById('ltc-forecast-end')?.value || '2040',
      region: document.getElementById('ltc-region')?.value || 'us',
      age_min: document.getElementById('ltc-age-min')?.value || '30',
      age_max: document.getElementById('ltc-age-max')?.value || '85',
      life_cover: document.getElementById('ltc-life-cover')?.value || '500000',
      ltc_annual_cover: document.getElementById('ltc-ltc-cover')?.value || '60000',
      adl_threshold: document.getElementById('ltc-adl')?.value || '3',
      coverage_type: document.getElementById('ltc-coverage-type')?.value || 'hybrid_life_ltc',
      hedge_share_pct: document.getElementById('ltc-hedge')?.value || '35',
      lives: document.getElementById('ltc-lives')?.value || '10000',
      mortality_improvement_pct: document.getElementById('ltc-mort-imp')?.value || '0.5',
      ltc_incidence_load_pct: document.getElementById('ltc-inc-load')?.value || '0',
      duration_stress_pct: document.getElementById('ltc-dur-stress')?.value || '0',
    };
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
    return `<tr><td colspan="${cols}" style="text-align:center;color:var(--text-light);">${message}</td></tr>`;
  }

  function renderKpis(pack) {
    const k = pack.kpis || {};
    const set = (id, text) => {
      const el = document.getElementById(id);
      if (el) el.textContent = text;
    };
    set('ltc-kpi-life-index', k.life_premium_index_end == null ? '—' : num(k.life_premium_index_end, 1));
    set('ltc-kpi-ltc-index', k.ltc3_premium_index_end == null ? '—' : num(k.ltc3_premium_index_end, 1));
    set('ltc-kpi-life-app', k.life_appetite_now_pct == null ? '—' : pct(k.life_appetite_now_pct));
    set('ltc-kpi-hybrid-app', k.hybrid_appetite_now_pct == null ? '—' : pct(k.hybrid_appetite_now_pct));
    set('ltc-kpi-ltc-app', k.ltc3_appetite_now_pct == null ? '—' : pct(k.ltc3_appetite_now_pct));
    set('ltc-kpi-ceded', k.net_ceded_exposure == null ? '—' : money(k.net_ceded_exposure));
  }

  function renderNarrative(pack) {
    const el = document.getElementById('ltc-narrative');
    if (!el) return;
    const lines = pack.narrative || [];
    el.innerHTML = lines.map((line) => `<p style="margin-bottom:8px;">${line}</p>`).join('')
      || '<p style="color:var(--text-light);">No narrative.</p>';
  }

  function renderSources(pack) {
    const el = document.getElementById('ltc-sources');
    if (!el) return;
    el.innerHTML = (pack.sources || []).map((src) => {
      const href = src.url && String(src.url).startsWith('http')
        ? `<a href="${src.url}" target="_blank" rel="noopener">${src.source}</a>`
        : `<strong>${src.source}</strong>`;
      return `<li>${href} · ${src.published_year || ''} · ${src.period_covered || ''}<br>`
        + `<span style="color:var(--text-light);">${src.headline_metric || ''}</span></li>`;
    }).join('');
  }

  function renderHistory(rows) {
    if (!rows || !rows.length) {
      fillBody('ltc-history-table', emptyRow(9, 'No historical rows for this window.'));
      return;
    }
    const sampled = rows.filter((r, i) => r.year % 5 === 0 || i === 0 || i === rows.length - 1);
    fillBody('ltc-history-table', sampled.map((r) => `
      <tr>
        <td>${r.year}</td>
        <td>${r.era || ''}</td>
        <td>${num(r.life_premium_index, 1)}</td>
        <td>${num(r.ltc3_premium_index, 1)}</td>
        <td>${pct(r.life_appetite_pct)}</td>
        <td>${pct(r.ltc3_appetite_pct)}</td>
        <td>${pct(r.hybrid_appetite_pct)}</td>
        <td>${num(r.capacity_index, 1)}</td>
        <td>${r.preferred_structure || ''}</td>
      </tr>
    `).join(''));
  }

  function renderAgeCover(rows) {
    if (!rows || !rows.length) {
      fillBody('ltc-age-cover-table', emptyRow(8, 'No age bands in range.'));
      return;
    }
    fillBody('ltc-age-cover-table', rows.map((r) => `
      <tr>
        <td>${band(r)}</td>
        <td>${money(r.recommended_life_cover)}</td>
        <td>${money(r.recommended_ltc_annual_cover)}</td>
        <td>${num(r.life_rate_per_1000, 3)}</td>
        <td>${num(r.ltc3_rate_per_1000, 3)}</td>
        <td>${money(r.life_annual_premium)}</td>
        <td>${money(r.ltc3_annual_premium)}</td>
        <td>${money(r.combined_annual_premium)}</td>
      </tr>
    `).join(''));
  }

  function renderCrossRisk(rows) {
    if (!rows || !rows.length) {
      fillBody('ltc-cross-risk-table', emptyRow(8, 'No cross-risk rows.'));
      return;
    }
    fillBody('ltc-cross-risk-table', rows.map((r) => `
      <tr>
        <td>${band(r)}</td>
        <td>${num(r.healthy_life_expectancy, 1)}y</td>
        <td>${num(r.remaining_le_after_3adl, 1)}y</td>
        <td>${num(r.le_reduction_years, 1)}y</td>
        <td>${num(r.excess_mortality_multiple, 2)}×</td>
        <td>${pct(100 * Number(r.p_death_within_5y_given_3adl || 0), 1)}</td>
        <td>${num(r.frailty_correlation, 2)}</td>
        <td>${r.hedge_implication || ''}</td>
      </tr>
    `).join(''));
  }

  function renderExposure(rows, totals) {
    if (!rows || !rows.length) {
      fillBody('ltc-exposure-table', emptyRow(10, 'No exposure rows.'));
      return;
    }
    fillBody('ltc-exposure-table', rows.map((r) => `
      <tr>
        <td>${band(r)}</td>
        <td>${Number(r.band_lives || 0).toLocaleString('en-US')}</td>
        <td>${money(r.expected_life_claims)}</td>
        <td>${money(r.expected_ltc_claims)}</td>
        <td>${money(r.ceded_life_exposure)}</td>
        <td>${money(r.ceded_ltc_exposure)}</td>
        <td>${money(r.joint_credit)}</td>
        <td>${money(r.net_ceded_exposure)}</td>
        <td>${money(r.tail_99_exposure)}</td>
        <td>${num(r.mean_claim_duration_years, 1)}y</td>
      </tr>
    `).join(''));
    const tot = totals || {};
    const el = document.getElementById('ltc-exposure-totals');
    if (el) {
      el.textContent = `Book total — expected life ${money(tot.expected_life_claims)} · expected 3+ADL ${money(tot.expected_ltc_claims)} · net ceded ${money(tot.net_ceded_exposure)} · 99% tail ${money(tot.tail_99_exposure)}.`;
    }
  }

  function renderForecast(rows) {
    if (!rows || !rows.length) {
      fillBody('ltc-forecast-table', emptyRow(9, 'No forecast rows.'));
      return;
    }
    const sampled = rows.filter((r, i) => r.year % 5 === 0 || i === 0 || i === rows.length - 1);
    fillBody('ltc-forecast-table', sampled.map((r) => `
      <tr>
        <td>${r.year}</td>
        <td>${pct(100 * r.mix_standalone_ltc, 1)}</td>
        <td>${pct(100 * r.mix_indemnity, 1)}</td>
        <td>${pct(100 * r.mix_reimbursement, 1)}</td>
        <td>${pct(100 * r.mix_hybrid_life_ltc, 1)}</td>
        <td>${pct(100 * r.mix_adb_rider, 1)}</td>
        <td>${pct(r.life_appetite_pct)}</td>
        <td>${pct(r.ltc3_appetite_pct)}</td>
        <td>${r.recommended_hedge || ''}</td>
      </tr>
    `).join(''));
  }

  function renderPricing(rows) {
    if (!rows || !rows.length) {
      fillBody('ltc-pricing-table', emptyRow(8, 'No pricing overlay.'));
      return;
    }
    fillBody('ltc-pricing-table', rows.map((r) => `
      <tr>
        <td>${band(r)}</td>
        <td>${num(r.life_rate_per_1000, 3)}</td>
        <td>${num(r.ltc3_rate_per_1000, 3)}</td>
        <td>${num(r.life_technical_rate_per_1000, 3)}</td>
        <td>${num(r.ltc3_technical_rate_per_1000, 3)}</td>
        <td>${num(r.joint_credit, 2)}</td>
        <td>${num(r.reinsurance_load, 3)}</td>
        <td>${num(r.mean_claim_duration_years, 1)}y</td>
      </tr>
    `).join(''));
  }

  function destroyChart(chart) {
    if (chart && typeof chart.destroy === 'function') {
      try { chart.destroy(); } catch (err) { /* ignore */ }
    }
  }

  function renderCharts(pack) {
    if (typeof Chart === 'undefined') return;
    const hist = (pack.tables || {}).historical_appetite || [];
    const forecast = (pack.tables || {}).coverage_forecast || [];
    const histCanvas = document.getElementById('ltc-history-chart');
    const forecastCanvas = document.getElementById('ltc-forecast-chart');

    destroyChart(historyChart);
    destroyChart(forecastChart);
    historyChart = null;
    forecastChart = null;

    if (histCanvas && hist.length) {
      historyChart = new Chart(histCanvas, {
        type: 'line',
        data: {
          labels: hist.map((r) => r.year),
          datasets: [
            { label: 'Life premium idx', data: hist.map((r) => r.life_premium_index), borderColor: '#2b6cb0', tension: 0.2, pointRadius: 0 },
            { label: '3+ADL premium idx', data: hist.map((r) => r.ltc3_premium_index), borderColor: '#d69e2e', tension: 0.2, pointRadius: 0 },
            { label: 'Life appetite %', data: hist.map((r) => r.life_appetite_pct), borderColor: '#38a169', tension: 0.2, pointRadius: 0, yAxisID: 'y1' },
            { label: '3+ADL appetite %', data: hist.map((r) => r.ltc3_appetite_pct), borderColor: '#e53e3e', tension: 0.2, pointRadius: 0, yAxisID: 'y1' },
            { label: 'Hybrid appetite %', data: hist.map((r) => r.hybrid_appetite_pct), borderColor: '#805ad5', tension: 0.2, pointRadius: 0, yAxisID: 'y1' },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          scales: {
            y: { title: { display: true, text: 'Index (1990 = 100)' } },
            y1: { position: 'right', title: { display: true, text: 'Appetite %' }, grid: { drawOnChartArea: false } },
          },
        },
      });
    }

    if (forecastCanvas && forecast.length) {
      forecastChart = new Chart(forecastCanvas, {
        type: 'bar',
        data: {
          labels: forecast.map((r) => r.year),
          datasets: [
            { label: 'Standalone', data: forecast.map((r) => 100 * r.mix_standalone_ltc), backgroundColor: 'rgba(229, 62, 62, 0.65)', stack: 'mix' },
            { label: 'Indemnity', data: forecast.map((r) => 100 * r.mix_indemnity), backgroundColor: 'rgba(214, 158, 46, 0.65)', stack: 'mix' },
            { label: 'Reimbursement', data: forecast.map((r) => 100 * r.mix_reimbursement), backgroundColor: 'rgba(66, 153, 225, 0.55)', stack: 'mix' },
            { label: 'Hybrid life+LTC', data: forecast.map((r) => 100 * r.mix_hybrid_life_ltc), backgroundColor: 'rgba(56, 161, 105, 0.7)', stack: 'mix' },
            { label: 'ADB rider', data: forecast.map((r) => 100 * r.mix_adb_rider), backgroundColor: 'rgba(128, 90, 213, 0.7)', stack: 'mix' },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            x: { stacked: true },
            y: { stacked: true, max: 100, title: { display: true, text: 'Coverage mix %' } },
          },
        },
      });
    }
  }

  function renderIntegrity(pack) {
    const el = document.getElementById('ltc-integrity');
    if (!el) return;
    const integ = pack.integrity || {};
    const hash = integ.pack_hash || integ.tables_hash || '';
    const shortHash = hash ? `${hash.slice(0, 12)}…` : '—';
    const live = integ.uses_live_rate_tables ? 'live PHINS rate bands' : 'research curves only';
    el.textContent = `Integrity ${shortHash} · ${integ.historical_span_years || 0} historical years · exposure totals ${integ.exposure_totals_match ? 'reconcile' : 'FAIL'} · forecast mix ${integ.forecast_mix_normalised ? 'normalised' : 'FAIL'} · rates from ${live}.`;
  }

  function render(pack) {
    lastPack = pack;
    const tables = pack.tables || {};
    renderKpis(pack);
    renderNarrative(pack);
    renderSources(pack);
    renderHistory(tables.historical_appetite);
    renderAgeCover(tables.age_cover_matrix);
    renderCrossRisk(tables.cross_risk_adl_mortality);
    renderExposure(tables.reinsurance_exposure, pack.exposure_totals);
    renderForecast(tables.coverage_forecast);
    renderPricing(tables.pricing_overlay);
    renderCharts(pack);
    renderIntegrity(pack);
    const cover = pack.coverage_label || pack.params?.coverage_type || '';
    setStatus(`Study ${pack.study_id} · ${cover} · recommended hedge ${pack.recommended_hedge || '—'}.`);
  }

  async function load() {
    const section = document.getElementById('section-ltc-life-research');
    if (!section) return lastPack;
    setStatus('Calculating 50-year study…');
    const requestId = Symbol('ltc-load');
    inflight = requestId;
    try {
      const res = await fetch(`/api/actuarial/ltc-life-research?${queryString()}`, {
        headers: authHeaders(),
      });
      const data = await res.json();
      if (inflight !== requestId) return lastPack;
      if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
      render(data);
      return data;
    } catch (err) {
      if (inflight === requestId) {
        setStatus(`Failed: ${err.message}`, true);
      }
      return null;
    }
  }

  function reset() {
    const defaults = {
      'ltc-year-from': '1975',
      'ltc-year-to': '2025',
      'ltc-forecast-end': '2040',
      'ltc-region': 'us',
      'ltc-age-min': '30',
      'ltc-age-max': '85',
      'ltc-life-cover': '500000',
      'ltc-ltc-cover': '60000',
      'ltc-adl': '3',
      'ltc-coverage-type': 'hybrid_life_ltc',
      'ltc-hedge': '35',
      'ltc-lives': '10000',
      'ltc-mort-imp': '0.5',
      'ltc-inc-load': '0',
      'ltc-dur-stress': '0',
    };
    Object.keys(defaults).forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.value = defaults[id];
    });
    return load();
  }

  async function download(fmt) {
    const table = document.getElementById('ltc-download-table')?.value || 'pricing_overlay';
    const format = fmt === 'json' ? 'json' : 'csv';
    try {
      const res = await fetch(
        `/api/actuarial/ltc-life-research/download?${queryString({ table, format })}`,
        { headers: authHeaders() },
      );
      if (!res.ok) {
        let message = `HTTP ${res.status}`;
        try {
          const body = await res.json();
          message = body.error || message;
        } catch (err) { /* ignore */ }
        throw new Error(message);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `phins-ltc-life-research-${table}.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setStatus(`Downloaded ${table} as ${format}.`);
    } catch (err) {
      setStatus(`Download failed: ${err.message}`, true);
    }
  }

  async function downloadPdf(lang) {
    const language = lang === 'he' ? 'he' : 'en';
    try {
      const res = await fetch(
        `/api/actuarial/ltc-life-research/download?${queryString({ format: 'pdf', lang: language })}`,
        { headers: authHeaders() },
      );
      if (!res.ok) {
        let message = `HTTP ${res.status}`;
        try {
          const body = await res.json();
          message = body.error || message;
        } catch (err) { /* ignore */ }
        throw new Error(message);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `phins-ltc-life-research-${language}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setStatus(language === 'he'
        ? 'Downloaded the full study PDF in Hebrew.'
        : 'Downloaded the full study PDF.');
    } catch (err) {
      setStatus(`PDF download failed: ${err.message}`, true);
    }
  }

  async function stage() {
    try {
      const res = await fetch('/api/actuarial/ltc-life-research/stage', {
        method: 'POST',
        headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
        body: JSON.stringify(collectParams()),
      });
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
      setStatus('Overlay staged for further use. Live rates were not changed. Download CSV to promote via Uploaded Tables if you want a cohort-scoped trial.');
      return data;
    } catch (err) {
      setStatus(`Stage failed: ${err.message}`, true);
      return null;
    }
  }

  async function promote() {
    const confirmed = window.confirm(
      'Promote the 3+ADL technical disability rates into the live actuarial table? '
      + 'This creates a new sub-version. Restore from Version History if it was not intended.',
    );
    if (!confirmed) return null;
    try {
      const payload = Object.assign({}, collectParams(), {
        table_types: ['disability_incidence_rates'],
      });
      const res = await fetch('/api/actuarial/ltc-life-research/promote', {
        method: 'POST',
        headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
      setStatus(data.warning || '3+ADL disability overlay promoted into the live table.');
      if (typeof loadTables === 'function') {
        try { loadTables(); } catch (err) { /* ignore */ }
      }
      return data;
    } catch (err) {
      setStatus(`Promote failed: ${err.message}`, true);
      return null;
    }
  }

  root.PhinsLtcLifeResearch = {
    load,
    reset,
    download,
    downloadPdf,
    stage,
    promote,
    collectParams,
    lastPack() { return lastPack; },
  };
})(typeof window !== 'undefined' ? window : globalThis);
