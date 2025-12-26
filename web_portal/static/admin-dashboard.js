// Admin dashboard: real data only (no fake seeded rows)

function getToken() {
  // Prefer the admin/staff token if present (avoids "admin sees customer view" when both exist).
  return localStorage.getItem('phins_admin_token') || localStorage.getItem('phins_token');
}

function getAuthHeaders() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function badge(status) {
  const s = String(status || '').toLowerCase();
  const cls = s.includes('active') || s === 'active' ? 'badge badge-active'
    : (s.includes('pending') || s === 'pending' ? 'badge badge-pending' : 'badge badge-inactive');
  return `<span class="${cls}">${String(status || 'unknown')}</span>`;
}

function esc(s) {
  return String(s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

async function requireAdmin() {
  const token = getToken();
  if (!token) {
    window.location.href = '/login.html';
    return null;
  }
  const resp = await fetch('/api/profile', { headers: getAuthHeaders() });
  if (resp.status === 401) {
    alert('Session expired. Please log in again.');
    localStorage.removeItem('phins_token');
    localStorage.removeItem('phins_admin_token');
    window.location.href = '/login.html';
    return null;
  }
  const prof = await resp.json().catch(() => ({}));
  if (!prof || !['admin'].includes(String(prof.role || '').toLowerCase())) {
    alert('Admin access required.');
    // Do not dump users into customer view on auth mismatch.
    window.location.href = '/login.html';
    return null;
  }
  return prof;
}

async function loadMetrics() {
  const data = await fetch('/api/metrics', { headers: getAuthHeaders() }).then(r => r.json());
  const m = data.metrics || {};
  document.getElementById('stat-customers').textContent = String((m.customers && m.customers.total) || 0);
  document.getElementById('stat-active-policies').textContent = String((m.policies && m.policies.active) || 0);
  document.getElementById('stat-uw-pending').textContent = String((m.underwriting && m.underwriting.pending) || 0);

  const openClaims = (m.claims && m.claims.pending) || 0;
  document.getElementById('stat-claims-open').textContent = String(openClaims);

  const pendingPolicies = (m.policies && m.policies.pending) || 0;
  const outstanding = (m.billing && m.billing.outstanding) || 0;
  const exposure = (m.actuary && m.actuary.total_exposure) || 0;
  const disExposure = (m.actuary && m.actuary.disability_exposure) || 0;

  const money0 = (x) => '$' + Number(x || 0).toLocaleString(undefined, { maximumFractionDigits: 0 });
  const elPending = document.getElementById('stat-policies-pending');
  if (elPending) elPending.textContent = String(pendingPolicies);
  const elOut = document.getElementById('stat-billing-outstanding');
  if (elOut) elOut.textContent = String(outstanding);
  const elExp = document.getElementById('stat-actuary-exposure');
  if (elExp) elExp.textContent = money0(exposure);
  const elDisExp = document.getElementById('stat-actuary-disability-exposure');
  if (elDisExp) elDisExp.textContent = money0(disExposure);
}

async function loadPipeline() {
  const data = await fetch('/api/underwriting', { headers: getAuthHeaders() }).then(r => r.json());
  // This table is explicitly "New Applications" – hide decisions already made.
  const items = (Array.isArray(data.items) ? data.items : []).filter(u => ['pending', 'draft'].includes(String(u.status || '').toLowerCase()));
  const tbody = document.getElementById('uw-table');
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="8" style="color:var(--muted)">No underwriting applications yet.</td></tr>';
    return;
  }

  async function approve(id) {
    const resp = await fetch('/api/underwriting/approve', {
      method: 'POST',
      headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, approved_by: 'admin' }),
    });
    const j = await resp.json().catch(() => ({}));
    if (!resp.ok || j.error) {
      alert(`Approve failed: ${j.error || 'Unknown error'}`);
      return;
    }
    // Surface created artifacts so the operator can validate the pipeline immediately.
    try {
      const p = j.policy || {};
      const lines = [
        `Policy created: ${p.id || '-'}`,
        `Status: ${p.status || '-'}`,
        p.billing_link_url ? `Billing link (48h): ${p.billing_link_url}` : null,
        p.nft_token ? `NFT token: ${p.nft_token}` : null,
        p.policy_terms_url ? `Policy PDF: ${p.policy_terms_url}` : null,
        p.policy_terms_csv_url ? `Policy CSV: ${p.policy_terms_csv_url}` : null,
      ].filter(Boolean);
      if (lines.length) alert(lines.join('\n'));
    } catch (_) {}
    await loadPipeline();
    await loadBillingPendingPolicies();
  }

  async function reject(id) {
    const reason = prompt('Rejection reason:');
    if (!reason) return;
    await fetch('/api/underwriting/reject', {
      method: 'POST',
      headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, rejected_by: 'admin', reason }),
    });
    await loadPipeline();
  }

  async function view(id) {
    const out = document.getElementById('uw-detail');
    if (out) out.textContent = 'Loading details…';
    try {
      const resp = await fetch(`/api/underwriting/details?id=${encodeURIComponent(id)}`, { headers: getAuthHeaders() });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || 'Failed');
      const c = data.customer || {};
      const p = data.policy || {};
      const pricing = data.pricing || (data.notes && data.notes.pricing) || {};
      const form = data.form || (data.notes && data.notes.form) || {};
      const monthly = Number((p && p.monthly_premium) || (pricing && pricing.monthly_total_premium) || 0);
      const savingsPct = (p && p.savings_percentage) ?? (pricing && pricing.savings_percentage_percent);
      const healthScore = (p && p.health_condition_score) ?? (pricing && pricing.health_condition_score);
      const healthLoad = (pricing && pricing.health_risk_loading_percent) ?? ((p && p.health_risk_loading_factor) ? Number(p.health_risk_loading_factor) * 100 : 0);
      const projId = `uw-proj-${String(id).replace(/[^a-zA-Z0-9_-]/g, '')}`;

      if (out) {
        out.innerHTML = `
          <div style="display:flex; gap:12px; flex-wrap:wrap">
            <div class="card" style="flex:1; min-width:260px">
              <div style="font-weight:900">Customer</div>
              <div style="margin-top:6px"><strong>${c.name || '-'}</strong></div>
              <div style="color:var(--muted)">${c.email || '-'}</div>
              <div><strong>ID:</strong> ${c.id || '-'}</div>
            </div>
            <div class="card" style="flex:1; min-width:260px">
              <div style="font-weight:900">Policy request</div>
              <div style="margin-top:6px"><strong>Coverage:</strong> $${Number(p.coverage_amount || 0).toLocaleString()}</div>
              <div><strong>Monthly premium:</strong> $${monthly.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
              <div><strong>Savings %:</strong> ${savingsPct ?? '-'}%</div>
              <div><strong>Jurisdiction:</strong> ${p.jurisdiction || '-'}</div>
              <div style="color:var(--muted); margin-top:6px">Health score: ${healthScore ?? '-'} (risk loading: ${Number(healthLoad || 0).toFixed(0)}%)</div>
            </div>
          </div>
          <div class="card" style="margin-top:12px">
            <div style="font-weight:900">Savings projection (benchmark)</div>
            <div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top:8px">
              <a class="btn-small" href="/api/admin/underwriting/projection/export?id=${encodeURIComponent(id)}&format=csv" target="_blank">Export CSV</a>
              <a class="btn-small" href="/api/admin/underwriting/projection/export?id=${encodeURIComponent(id)}&format=pdf" target="_blank">Export PDF</a>
              <div id="${projId}" style="color:var(--muted); margin-left:auto">Loading…</div>
            </div>
          </div>
          <details style="margin-top:10px">
            <summary style="cursor:pointer; font-weight:800">Full application form (stored)</summary>
            <pre style="white-space:pre-wrap; margin-top:10px; background:var(--bg); padding:12px; border-radius:10px; border:1px solid var(--border)">${esc(JSON.stringify(form || {}, null, 2))}</pre>
          </details>
          <details style="margin-top:10px">
            <summary style="cursor:pointer; font-weight:800">Pricing breakdown</summary>
            <pre style="white-space:pre-wrap; margin-top:10px; background:var(--bg); padding:12px; border-radius:10px; border:1px solid var(--border)">${esc(JSON.stringify(pricing || {}, null, 2))}</pre>
          </details>
        `;
      }

      // Fetch projection using the same pricing inputs (admin-authenticated)
      try {
        const age = (function(dob) {
          try {
            const dd = new Date(String(dob || ''));
            if (Number.isNaN(dd.getTime())) return null;
            const now = new Date();
            let a = now.getFullYear() - dd.getFullYear();
            const m = now.getMonth() - dd.getMonth();
            if (m < 0 || (m === 0 && now.getDate() < dd.getDate())) a--;
            return a;
          } catch (_) { return null; }
        })(c.dob);
        const years = Number(p.policy_term_years || (data.notes && data.notes.policy_term_years) || 15);
        const qs = new URLSearchParams();
        qs.set('type', String(p.type || 'disability'));
        qs.set('coverage_amount', String(p.coverage_amount || 100000));
        qs.set('age', String(age || 30));
        qs.set('jurisdiction', String(p.jurisdiction || 'US'));
        qs.set('savings_percentage', String(p.savings_percentage ?? 25));
        qs.set('operational_reinsurance_load', String(p.operational_reinsurance_load ?? 50));
        qs.set('health_condition_score', String(p.health_condition_score ?? 3));
        qs.set('years', String(Number.isFinite(years) ? years : 15));
        const pr = await fetch(`/api/projections/savings?${qs.toString()}`, { headers: getAuthHeaders() });
        const pj = await pr.json().catch(() => ({}));
        const target = document.getElementById(projId);
        if (!target) return;
        if (!pr.ok || pj.error) {
          target.textContent = 'Projection unavailable.';
          return;
        }
        const arr = Array.isArray(pj.projection) ? pj.projection : [];
        const monthlySav = Number(pj.monthly_savings_allocation || 0);
        target.innerHTML = `
          <div style="color:var(--muted)">Term: ${Number(pj.inputs?.years || years || 15)}y • Monthly savings: <strong>$${monthlySav.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}</strong></div>
          <div style="display:flex; gap:12px; flex-wrap:wrap; margin-top:10px">
            ${arr.map(x => `<div class="card" style="padding:10px 12px">
              <div style="font-weight:800">${x.scenario}</div>
              <div style="color:var(--muted); font-size:12px">${Number(x.annual_return_percent||0).toFixed(0)}%/yr</div>
              <div style="margin-top:6px; font-weight:900">$${Number(x.future_value||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}</div>
            </div>`).join('')}
          </div>
        `;
      } catch (e) {}
    } catch (e) {
      if (out) out.textContent = 'Could not load details.';
    }
  }

  const rows = items
    .sort((a, b) => String(b.submitted_date || '').localeCompare(String(a.submitted_date || '')))
    .slice(0, 50)
    .map(u => {
      let source = '-';
      try {
        if (u.notes) {
          const n = typeof u.notes === 'string' ? JSON.parse(u.notes) : u.notes;
          source = n && n.source ? String(n.source) : '-';
          if (n && n.auto_approved) source = source + ' (auto)';
        }
      } catch (e) {}
      const canAct = String(u.status || '').toLowerCase() === 'pending';
      const actions = `
        <button class="btn-small" onclick="window.__uwView('${u.id}')">View</button>
        ${canAct ? `<button class="btn-small" style="margin-left:8px" onclick="window.__uwApprove('${u.id}')">Approve</button>
                    <button class="btn-small" style="margin-left:8px" onclick="window.__uwReject('${u.id}')">Reject</button>` : `<span style="color:var(--muted); margin-left:8px">—</span>`}
      `;
      return `
      <tr>
        <td>${u.id || '-'}</td>
        <td>${u.policy_id || '-'}</td>
        <td>${u.customer_id || '-'}</td>
        <td>${source}</td>
        <td>${badge(u.status || 'pending')}</td>
        <td>${u.risk_assessment ? badge(u.risk_assessment) : '-'}</td>
        <td>${u.submitted_date ? new Date(u.submitted_date).toLocaleString() : '-'}</td>
        <td>${actions}</td>
      </tr>
    `;
    });
  tbody.innerHTML = rows.join('');

  // Expose handlers for inline onclick (keeps file dependency-free)
  window.__uwApprove = approve;
  window.__uwReject = reject;
  window.__uwView = view;
}

function _fmtDeadline(iso) {
  try {
    if (!iso) return '-';
    const d = new Date(String(iso));
    if (Number.isNaN(d.getTime())) return '-';
    const hrs = Math.max(0, (d.getTime() - Date.now()) / 36e5);
    return `${d.toLocaleString()} (${hrs.toFixed(1)}h left)`;
  } catch (_) {
    return '-';
  }
}

async function loadBillingPendingPolicies() {
  const tbody = document.getElementById('billing-pending-table');
  if (!tbody) return;
  try {
    const resp = await fetch('/api/policies?page=1&page_size=500', { headers: getAuthHeaders() });
    const data = await resp.json().catch(() => ({}));
    const items = Array.isArray(data.items) ? data.items : [];
    const pending = items.filter(p => String(p.status || '').toLowerCase() === 'billing_pending');
    if (!pending.length) {
      tbody.innerHTML = '<tr><td colspan="6" style="color:var(--muted)">No billing-pending policies right now.</td></tr>';
      return;
    }
    tbody.innerHTML = pending
      .sort((a, b) => String(a.billing_link_expires || '').localeCompare(String(b.billing_link_expires || '')))
      .slice(0, 100)
      .map(p => {
        const artifacts = [
          p.billing_link_url ? `<a class="link" href="${p.billing_link_url}" target="_blank">Billing link</a>` : null,
          p.policy_terms_url ? `<a class="link" href="${p.policy_terms_url}" target="_blank">Terms PDF</a>` : null,
          p.policy_package_url ? `<a class="link" href="${p.policy_package_url}" target="_blank">Package PDF</a>` : null,
          p.policy_terms_csv_url ? `<a class="link" href="${p.policy_terms_csv_url}" target="_blank">Terms CSV</a>` : null,
        ].filter(Boolean).join(' • ');
        return `
          <tr>
            <td>${p.id || '-'}</td>
            <td>${p.customer_id || '-'}</td>
            <td>${badge(p.status || 'billing_pending')}</td>
            <td>${_fmtDeadline(p.billing_link_expires)}</td>
            <td>${p.nft_token ? `<span style="font-family:monospace">${p.nft_token}</span>` : '-'}</td>
            <td>${artifacts || '<span style="color:var(--muted)">—</span>'}</td>
          </tr>
        `;
      }).join('');
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="6" style="color:var(--muted)">Unable to load policies.</td></tr>';
  }
}

async function loadUwAutomationConfig() {
  const msg = document.getElementById('uw-auto-msg');
  try {
    const data = await fetch('/api/underwriting/automation/config', { headers: getAuthHeaders() }).then(r => r.json());
    const cfg = data.config || {};
    const enabled = String(cfg.enabled ?? true);
    const maxAge = cfg.max_age ?? 30;
    const maxCov = cfg.max_coverage_amount ?? 250000;
    const policyType = cfg.policy_type ?? 'disability';
    const maxAdlRiskRate = cfg.max_adl_actuarial_risk_rate ?? 0.03;
    const sel = document.getElementById('uw-auto-enabled');
    const age = document.getElementById('uw-auto-max-age');
    const cov = document.getElementById('uw-auto-max-coverage');
    const ptype = document.getElementById('uw-auto-policy-type');
    const adl = document.getElementById('uw-auto-max-adl-risk');
    if (sel) sel.value = enabled === 'false' ? 'false' : 'true';
    if (age) age.value = String(maxAge);
    if (cov) cov.value = String(maxCov);
    if (ptype) ptype.value = String(policyType);
    if (adl) adl.value = String(Number(maxAdlRiskRate) * 100);
    if (msg) msg.textContent = '';
  } catch (e) {
    if (msg) msg.textContent = 'Automation config unavailable.';
  }
}

async function saveUwAutomationConfig() {
  const msg = document.getElementById('uw-auto-msg');
  const enabled = document.getElementById('uw-auto-enabled')?.value === 'true';
  const maxAge = Number(document.getElementById('uw-auto-max-age')?.value || 30);
  const maxCov = Number(document.getElementById('uw-auto-max-coverage')?.value || 250000);
  const policyType = String(document.getElementById('uw-auto-policy-type')?.value || 'disability');
  const maxAdlRiskPct = Number(document.getElementById('uw-auto-max-adl-risk')?.value || 3);
  const maxAdlRiskRate = maxAdlRiskPct / 100;
  try {
    const resp = await fetch('/api/underwriting/automation/config', {
      method: 'POST',
      headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled, max_age: maxAge, max_coverage_amount: maxCov, policy_type: policyType, max_adl_actuarial_risk_rate: maxAdlRiskRate }),
    });
    const data = await resp.json();
    if (!resp.ok || !data.success) throw new Error(data.error || 'Save failed');
    if (msg) msg.textContent = 'Saved.';
    setTimeout(() => { if (msg) msg.textContent = ''; }, 2000);
  } catch (e) {
    if (msg) msg.textContent = 'Save failed.';
  }
}

async function uploadUwAutomationConfig() {
  const msg = document.getElementById('uw-auto-msg');
  const file = document.getElementById('uw-auto-file')?.files?.[0];
  if (!file) {
    if (msg) msg.textContent = 'Choose a file first.';
    return;
  }
  try {
    const text = await file.text();
    // For CSV uploads, support specifying max_adl_actuarial_risk_rate as either a fraction (0.03)
    // or percentage (3). The server stores fraction.
    const payload = file.name.toLowerCase().endsWith('.csv')
      ? { csv: text }
      : { json: text };
    const resp = await fetch('/api/underwriting/automation/config/import', {
      method: 'POST',
      headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok || !data.success) throw new Error(data.error || 'Upload failed');
    if (msg) msg.textContent = 'Uploaded.';
    await loadUwAutomationConfig();
    setTimeout(() => { if (msg) msg.textContent = ''; }, 2000);
  } catch (e) {
    if (msg) msg.textContent = 'Upload failed.';
  }
}

async function loadActuarialTable() {
  const j = document.getElementById('actuarial-jurisdiction').value || 'US';
  const data = await fetch(`/api/actuarial/disability-table?jurisdiction=${encodeURIComponent(j)}&age_min=18&age_max=80`, { headers: getAuthHeaders() }).then(r => r.json());
  const items = Array.isArray(data.items) ? data.items : [];
  const tbody = document.getElementById('actuarial-table');
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="2" style="color:var(--muted)">No actuarial data available.</td></tr>';
    return;
  }
  // Show a subset for readability (every 5 years) + always include age 50
  const subset = items.filter(r => r.age % 5 === 0 || r.age === 50);
  const rows = subset.map(r => `
    <tr>
      <td>${r.age}</td>
      <td>${Number(r.annual_adl_claim_rate_percent).toFixed(2)}%</td>
    </tr>
  `);
  tbody.innerHTML = rows.join('');
}

async function loadMarket() {
  const [crypto, indexes] = await Promise.all([
    fetch('/api/market/crypto?symbols=BTC,ETH,SOL&vs=USD', { headers: getAuthHeaders() }).then(r => r.json()),
    fetch('/api/market/indexes?symbols=SPX,NASDAQ,DOW,FTSE&currency=USD', { headers: getAuthHeaders() }).then(r => r.json()),
  ]);
  const c = crypto.items || [];
  const i = indexes.items || [];

  const el = document.getElementById('market-block');
  const parts = [];
  if (c.length) {
    parts.push('<div style="margin-bottom:10px"><strong>Crypto</strong></div>');
    parts.push('<div style="display:flex; flex-wrap:wrap; gap:12px; margin-bottom:16px;">' + c.map(q => `
      <div style="padding:10px 12px; border:1px solid var(--border); border-radius:10px; background:#fff;">
        <div style="font-weight:700">${q.symbol}</div>
        <div style="color:var(--muted)">$${Number(q.price).toLocaleString(undefined, {maximumFractionDigits: 4})}</div>
      </div>
    `).join('') + '</div>');
  }
  if (i.length) {
    parts.push('<div style="margin-bottom:10px"><strong>Indexes</strong></div>');
    parts.push('<div style="display:flex; flex-wrap:wrap; gap:12px;">' + i.map(q => `
      <div style="padding:10px 12px; border:1px solid var(--border); border-radius:10px; background:#fff;">
        <div style="font-weight:700">${q.symbol}</div>
        <div style="color:var(--muted)">${Number(q.price).toLocaleString(undefined, {maximumFractionDigits: 2})}</div>
      </div>
    `).join('') + '</div>');
  }
  el.innerHTML = parts.length ? parts.join('') : '<span style="color:var(--muted)">Market data unavailable.</span>';
}

async function loadAdminInvestmentAllocations() {
  const resp = await fetch('/api/admin/investments/allocations?currency=USD', { headers: getAuthHeaders() });
  return resp.json();
}

function renderAdminInvestmentAllocations(data) {
  const el = document.getElementById('admin-investment-allocations');
  if (!el) return;
  const totals = data.totals || {};
  const top = Array.isArray(data.top_allocations) ? data.top_allocations : [];
  if (!top.length) {
    el.innerHTML = '<span style="color:var(--muted)">No savings allocations recorded yet.</span>';
    return;
  }
  const rows = top.slice(0, 20).map((r) => {
    const amt = Number(r.amount || 0);
    return `
      <div style="display:flex; justify-content:space-between; gap:12px; padding:6px 0; border-bottom:1px solid var(--border)">
        <div><strong>${r.symbol}</strong> <span style="color:var(--muted); font-size:12px">${r.kind}</span></div>
        <div style="text-align:right"><strong>$${amt.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong> <span style="color:var(--muted); font-size:12px">${r.currency || data.currency || 'USD'}</span></div>
      </div>
    `;
  }).join('');
  el.innerHTML = `
    <div style="display:flex; gap:16px; flex-wrap:wrap">
      <div class="card" style="flex:1; min-width:260px">
        <div style="font-weight:900">Totals</div>
        <div style="margin-top:8px"><strong>Customers:</strong> ${Number(totals.customers || 0)}</div>
        <div><strong>Risk total:</strong> $${Number(totals.risk_total || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
        <div><strong>Savings total:</strong> $${Number(totals.savings_total || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
      </div>
      <div class="card" style="flex:2; min-width:320px">
        <div style="font-weight:900; margin-bottom:8px">Top savings basket exposures</div>
        ${rows}
      </div>
    </div>
  `;
}

async function loadPolicyTermsTemplate() {
  const ta = document.getElementById('policy-terms-template');
  const msg = document.getElementById('policy-terms-msg');
  if (!ta) return;
  try {
    const resp = await fetch('/api/admin/policy-terms/template', { headers: getAuthHeaders() });
    const j = await resp.json().catch(() => ({}));
    if (resp.ok && Array.isArray(j.lines)) {
      ta.value = j.lines.join('\n');
      if (msg) msg.textContent = '';
    } else {
      if (msg) msg.textContent = 'Template unavailable.';
    }
  } catch (_) {
    if (msg) msg.textContent = 'Template unavailable.';
  }
}

async function savePolicyTermsTemplate(text) {
  const msg = document.getElementById('policy-terms-msg');
  if (msg) msg.textContent = 'Saving…';
  const resp = await fetch('/api/admin/policy-terms/template', {
    method: 'POST',
    headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });
  const j = await resp.json().catch(() => ({}));
  if (!resp.ok || j.error) {
    if (msg) msg.textContent = 'Save failed.';
    alert(`Save failed: ${j.error || 'Unknown error'}`);
    return;
  }
  if (msg) msg.textContent = 'Saved.';
  setTimeout(() => { if (msg) msg.textContent = ''; }, 2000);
}

async function loadPolicyConditionsPdf() {
  const el = document.getElementById('policy-conditions-current');
  const msg = document.getElementById('policy-conditions-msg');
  if (!el) return;
  try {
    const resp = await fetch('/api/policy-terms/conditions', { headers: getAuthHeaders() });
    const j = await resp.json().catch(() => ({}));
    if (resp.ok && j && j.available) {
      const link = j.download_url ? `<a class="link" href="${j.download_url}" target="_blank">Download current conditions PDF</a>` : '';
      const hash = j.sha256 ? `<span style="font-family:monospace">SHA256: ${j.sha256}</span>` : '';
      el.innerHTML = `${link} ${hash}`;
      if (msg) msg.textContent = '';
    } else {
      el.innerHTML = '<span style="color:var(--muted)">No conditions PDF uploaded yet.</span>';
    }
  } catch (_) {
    if (msg) msg.textContent = 'Unable to load conditions PDF.';
  }
}

async function uploadPolicyConditionsPdf(file) {
  const msg = document.getElementById('policy-conditions-msg');
  if (!file) return;
  if (msg) msg.textContent = 'Uploading…';
  const fd = new FormData();
  fd.append('file', file, file.name);
  const resp = await fetch('/api/admin/policy-terms/conditions/upload', {
    method: 'POST',
    headers: { ...getAuthHeaders() },
    body: fd,
  });
  const j = await resp.json().catch(() => ({}));
  if (!resp.ok || !j.success) {
    if (msg) msg.textContent = 'Upload failed.';
    alert(`Upload failed: ${j.error || 'Unknown error'}`);
    return;
  }
  if (msg) msg.textContent = 'Uploaded.';
  await loadPolicyConditionsPdf();
  setTimeout(() => { if (msg) msg.textContent = ''; }, 2000);
}

// Language selector (same UX as other pages)
window.changeLanguage = function changeLanguage(lang) {
  localStorage.setItem('phins_language', lang);
  const notification = document.createElement('div');
  notification.style.cssText = 'position:fixed;top:80px;right:20px;background:#28a745;color:#fff;padding:16px 24px;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.2);z-index:1000;font-weight:600;';
  notification.textContent = 'Language changed to ' + document.getElementById('language-selector').selectedOptions[0].text;
  document.body.appendChild(notification);
  setTimeout(() => notification.remove(), 3000);
};

document.addEventListener('DOMContentLoaded', async () => {
  const savedLang = localStorage.getItem('phins_language');
  if (savedLang && document.getElementById('language-selector')) {
    document.getElementById('language-selector').value = savedLang;
  }

  const logoutBtn = document.querySelector('.btn-logout');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', (e) => {
      e.preventDefault();
      sessionStorage.clear();
      localStorage.removeItem('phins_token');
      localStorage.removeItem('phins_admin_token');
      window.location.href = '/';
    });
  }

  const prof = await requireAdmin();
  if (!prof) return;

  // Policy terms template (used for future approvals)
  await loadPolicyTermsTemplate();
  const termsSaveBtn = document.getElementById('policy-terms-save');
  if (termsSaveBtn) {
    termsSaveBtn.addEventListener('click', async () => {
      const ta = document.getElementById('policy-terms-template');
      const text = String(ta?.value || '').trim();
      if (!text) {
        alert('Please enter at least one condition line.');
        return;
      }
      await savePolicyTermsTemplate(text);
    });
  }
  const termsFile = document.getElementById('policy-terms-file');
  if (termsFile) {
    termsFile.addEventListener('change', async (e) => {
      try {
        const f = e.target?.files?.[0];
        if (!f) return;
        const text = String(await f.text());
        if (!text.trim()) return;
        await savePolicyTermsTemplate(text);
        await loadPolicyTermsTemplate();
      } catch (_) {}
    });
  }

  // Policy conditions master PDF upload + current status
  await loadPolicyConditionsPdf();
  const condBtn = document.getElementById('policy-conditions-upload');
  if (condBtn) {
    condBtn.addEventListener('click', async () => {
      const f = document.getElementById('policy-conditions-pdf')?.files?.[0];
      if (!f) { alert('Choose a PDF file first.'); return; }
      await uploadPolicyConditionsPdf(f);
    });
  }

  // Market: allow admin to push price points for charts (persisted server-side)
  const pushBtn = document.getElementById('market-push-btn');
  if (pushBtn) {
    pushBtn.addEventListener('click', async () => {
      const msg = document.getElementById('market-push-msg');
      const kind = String(document.getElementById('market-push-kind')?.value || 'crypto').toLowerCase();
      const symbol = String(document.getElementById('market-push-symbol')?.value || '').trim().toUpperCase();
      const price = Number(document.getElementById('market-push-price')?.value || 0);
      if (msg) msg.textContent = '';
      if (!symbol || !(price > 0)) {
        if (msg) msg.textContent = 'Enter symbol + price.';
        return;
      }
      if (msg) msg.textContent = 'Pushing…';
      try {
        const resp = await fetch('/api/market/push', {
          method: 'POST',
          headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ kind, symbol, price, currency: 'USD' }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.success) throw new Error(data.error || 'Push failed');
        if (msg) msg.textContent = `Pushed ${symbol}.`;
        // refresh charts immediately
        const refreshBtn = document.querySelector('#admin-market [data-role="refresh"]');
        if (refreshBtn) refreshBtn.click();
        setTimeout(() => { if (msg) msg.textContent = ''; }, 2000);
      } catch (e) {
        if (msg) msg.textContent = 'Push failed.';
      }
    });
  }

  const saveBtn = document.getElementById('uw-auto-save');
  if (saveBtn) saveBtn.addEventListener('click', saveUwAutomationConfig);
  const uploadBtn = document.getElementById('uw-auto-upload');
  if (uploadBtn) uploadBtn.addEventListener('click', uploadUwAutomationConfig);
  await loadUwAutomationConfig();

  // Support console: search + admin password reset
  const supportBtn = document.getElementById('support-search');
  const resetBtn = document.getElementById('reset-btn');

  async function supportSearch() {
    const email = String(document.getElementById('support-email')?.value || '').trim();
    const out = document.getElementById('support-result');
    if (!out) return;
    if (!email) {
      out.textContent = 'Enter an email address.';
      return;
    }
    out.textContent = 'Searching…';
    try {
      const resp = await fetch(`/api/customers/search?email=${encodeURIComponent(email)}`, { headers: getAuthHeaders() });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || 'Not found');

      const c = data.customer || {};
      const uw = Array.isArray(data.underwriting) ? data.underwriting : [];
      const pol = Array.isArray(data.policies) ? data.policies : [];
      const clm = Array.isArray(data.claims) ? data.claims : [];
      const bill = Array.isArray(data.billing) ? data.billing : [];

      out.innerHTML = `
        <div style="display:flex; gap:12px; flex-wrap:wrap">
          <div class="card" style="flex:1; min-width:260px">
            <div style="font-weight:800">Customer</div>
            <div style="color:var(--muted); margin-top:6px">${c.name || '-'}</div>
            <div><strong>ID:</strong> ${c.id || '-'}</div>
            <div><strong>Email:</strong> ${c.email || '-'}</div>
            <div><strong>Phone:</strong> ${c.phone || '-'}</div>
          </div>
          <div class="card" style="flex:1; min-width:220px">
            <div style="font-weight:800">Pipeline</div>
            <div style="margin-top:6px"><strong>Underwriting:</strong> ${uw.length}</div>
            <div><strong>Policies:</strong> ${pol.length}</div>
            <div><strong>Claims:</strong> ${clm.length}</div>
            <div><strong>Bills:</strong> ${bill.length}</div>
          </div>
        </div>
        <div style="margin-top:10px; color:var(--muted)">Tip: open <a class="link" href="/submissions/">Submissions</a> and filter by this email for full form history.</div>
      `;
    } catch (e) {
      out.textContent = 'Not found or access denied.';
    }
  }

  async function adminResetPassword() {
    const input = String(document.getElementById('reset-username')?.value || '').trim();
    const msg = document.getElementById('reset-msg');
    if (!input) {
      if (msg) msg.textContent = 'Enter username or email.';
      return;
    }
    if (msg) msg.textContent = 'Resetting…';
    try {
      const resp = await fetch('/api/admin/reset-password', {
        method: 'POST',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: input }),
      });
      const data = await resp.json();
      if (!resp.ok || !data.success) throw new Error(data.error || 'Reset failed');
      const tp = data.temporary_password ? ` Temp password: ${data.temporary_password}` : '';
      if (msg) msg.textContent = `Reset OK.${tp}`;
    } catch (e) {
      if (msg) msg.textContent = 'Reset failed.';
    }
  }

  if (supportBtn) supportBtn.addEventListener('click', supportSearch);
  if (resetBtn) resetBtn.addEventListener('click', adminResetPassword);

  document.getElementById('actuarial-refresh').addEventListener('click', loadActuarialTable);
  document.getElementById('actuarial-jurisdiction').addEventListener('change', loadActuarialTable);

  try {
    const [_, __, ___, ____, inv, _____] = await Promise.all([loadMetrics(), loadPipeline(), loadActuarialTable(), loadMarket(), loadAdminInvestmentAllocations(), loadBillingPendingPolicies()]);
    renderAdminInvestmentAllocations(inv || {});
  } catch (e) {
    console.error(e);
  }

  // Market charts (indexes + currencies) for admin
  try {
    if (typeof renderMarketCharts === 'function' && document.getElementById('admin-market')) {
      await renderMarketCharts('admin-market', { storeKeyCrypto: 'phins_admin_crypto', storeKeyIndex: 'phins_admin_index', intervalSeconds: 30 });
    }
  } catch (e) {}
});

