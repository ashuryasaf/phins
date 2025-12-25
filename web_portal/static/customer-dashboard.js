// Customer dashboard: real data only (no hardcoded demo rows)

function getToken() {
  return localStorage.getItem('phins_token');
}

function getAuthHeaders() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function money(x) {
  const n = Number(x || 0);
  return '$' + n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function calcAgeFromDob(dobStr) {
  try {
    const d = new Date(String(dobStr || ''));
    if (Number.isNaN(d.getTime())) return null;
    const now = new Date();
    let age = now.getFullYear() - d.getFullYear();
    const m = now.getMonth() - d.getMonth();
    if (m < 0 || (m === 0 && now.getDate() < d.getDate())) age--;
    return age;
  } catch (_) {
    return null;
  }
}

function badge(status) {
  const s = String(status || '').toLowerCase();
  const cls = s.includes('active') || s === 'active' ? 'badge badge-active'
    : (s.includes('pending') || s === 'pending' ? 'badge badge-pending' : 'badge badge-inactive');
  return `<span class="${cls}">${String(status || 'unknown')}</span>`;
}

function hoursLeft(iso) {
  try {
    if (!iso) return null;
    const t = new Date(String(iso));
    if (Number.isNaN(t.getTime())) return null;
    const ms = t.getTime() - Date.now();
    return Math.max(0, ms / 36e5);
  } catch (_) {
    return null;
  }
}

async function loadProfile() {
  const resp = await fetch('/api/profile', { headers: getAuthHeaders() });
  if (resp.status === 401) {
    window.location.href = '/login.html';
    return null;
  }
  const prof = await resp.json();
  // Hard separation: if a staff/admin account somehow lands here, send them to admin.
  const role = String(prof.role || '').toLowerCase();
  if (role && role !== 'customer') {
    window.location.href = '/admin.html';
    return null;
  }
  return prof;
}

async function loadPolicies() {
  const resp = await fetch('/api/policies?page=1&page_size=200', { headers: getAuthHeaders() });
  const data = await resp.json();
  return Array.isArray(data.items) ? data.items : [];
}

async function loadClaims() {
  const resp = await fetch('/api/claims?page=1&page_size=200', { headers: getAuthHeaders() });
  const data = await resp.json();
  return Array.isArray(data.items) ? data.items : [];
}

async function loadApplications() {
  const resp = await fetch('/api/underwriting', { headers: getAuthHeaders() });
  const data = await resp.json();
  return Array.isArray(data.items) ? data.items : [];
}

async function loadStatement() {
  const resp = await fetch('/api/statement', { headers: getAuthHeaders() });
  return resp.json();
}

async function loadNotifications() {
  const resp = await fetch('/api/notifications', { headers: getAuthHeaders() });
  const data = await resp.json();
  return Array.isArray(data.items) ? data.items : [];
}

async function loadInvestmentAllocations() {
  const resp = await fetch('/api/investments/allocations?currency=USD', { headers: getAuthHeaders() });
  return resp.json();
}

async function loadWalletBalance() {
  const resp = await fetch('/api/wallet/balance', { headers: getAuthHeaders() });
  return resp.json();
}

async function depositToWallet({ policy_id, amount }) {
  const resp = await fetch('/api/wallet/deposit', {
    method: 'POST',
    headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ policy_id, amount }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || 'Deposit failed');
  return data;
}

async function loadMarketSnapshot() {
  const [crypto, indexes] = await Promise.all([
    fetch('/api/market/crypto?symbols=BTC,ETH&vs=USD', { headers: getAuthHeaders() }).then(r => r.json()),
    fetch('/api/market/indexes?symbols=SPX,NASDAQ,DOW,FTSE&currency=USD', { headers: getAuthHeaders() }).then(r => r.json()),
  ]);
  return { crypto: crypto.items || [], indexes: indexes.items || [] };
}

function renderApplications(apps) {
  const tbody = document.getElementById('applications-table');
  // Once approved, billing is tracked under "My Policies" (billing_pending).
  const filtered = (apps || []).filter(a => !['approved'].includes(String(a.status || '').toLowerCase()));
  if (!filtered.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="color:var(--muted)">No applications in pipeline.</td></tr>';
    return;
  }
  let focusId = null;
  try {
    const u = new URL(window.location.href);
    focusId = u.searchParams.get('focus_application_id');
  } catch (_) {
    focusId = null;
  }
  const rows = filtered
    .sort((a, b) => String(b.submitted_date || '').localeCompare(String(a.submitted_date || '')))
    .slice(0, 50)
    .map(a => {
      const st = String(a.status || '').toLowerCase();
      const canEdit = st === 'pending' || st === 'draft';
      // For approved applications, billing is handled at the policy level (see "My Policies").
      const action = canEdit && a.id
        ? `<a class="link" href="/quote.html?application_id=${encodeURIComponent(a.id)}">${st === 'draft' ? 'Continue' : 'Edit'}</a>`
        : '<span style="color:var(--muted)">—</span>';
      const hl = (focusId && a.id && String(a.id) === String(focusId)) ? ' style="background:rgba(76,175,80,0.10)"' : '';
      return `
        <tr${hl}>
          <td>${a.id || '-'}</td>
          <td>${a.policy_id || '-'}</td>
          <td>${badge(a.status || 'pending')}</td>
          <td>${a.risk_assessment ? badge(a.risk_assessment) : '-'}</td>
          <td>${a.submitted_date ? new Date(a.submitted_date).toLocaleDateString() : '-'}</td>
          <td>${action}</td>
        </tr>
      `;
    });
  tbody.innerHTML = rows.join('');
}

function renderNotifications(items) {
  const el = document.getElementById('notifications-list');
  if (!el) return;
  if (!items.length) {
    el.innerHTML = '<span style="color:var(--muted)">No messages yet.</span>';
    return;
  }
  const rows = items.slice(0, 20).map(n => {
    const created = n.created_date ? new Date(n.created_date).toLocaleString() : '';
    const subj = n.subject || 'Notification';
    const msg = n.message || '';
    const link = n.link ? `<div style="margin-top:6px"><a class="link" href="${n.link}">Open link →</a></div>` : '';
    return `
      <div style="padding:12px 0; border-bottom:1px solid var(--border)">
        <div style="font-weight:700">${subj}</div>
        <div style="color:var(--muted); font-size:12px; margin-top:2px">${created}</div>
        <div style="margin-top:6px">${msg}</div>
        ${link}
      </div>
    `;
  }).join('');
  el.innerHTML = rows;
}

function renderPolicies(policies) {
  const tbody = document.getElementById('policies-table');
  if (!policies.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="color:var(--muted)">No policies yet.</td></tr>';
    return;
  }
  const rows = policies
    .sort((a, b) => String(b.created_date || '').localeCompare(String(a.created_date || '')))
    .slice(0, 100)
    .map(p => {
      const status = p.status || 'pending_underwriting';
      const invPct = p.savings_percentage ?? 25;
      const jurisdiction = p.jurisdiction || 'US';
      const monthly = p.monthly_premium ?? (p.annual_premium ? Number(p.annual_premium) / 12 : 0);
      const st = String(status || '').toLowerCase();
      let actions = `<span style="color:var(--muted)">${jurisdiction}</span>`;
      if (st === 'billing_pending' && p.billing_link_url) {
        const hrs = hoursLeft(p.billing_link_expires);
        const left = (hrs === null) ? '' : ` • ${(hrs).toFixed(1)}h left`;
        actions = `<a class="link" href="${p.billing_link_url}">Complete billing (48h)</a><span style="color:var(--muted)">${left}</span>`;
      } else if (p.policy_terms_url) {
        actions = `<a class="link" href="${p.policy_terms_url}" target="_blank">Policy terms (PDF)</a>`;
      }
      // Modular allocation: allow changing savings% (affects future risk/savings split).
      if (['active','billing_pending','billing_review'].includes(st)) {
        actions += ` <button class="btn-small" style="margin-left:8px" onclick="window.__updateAllocation('${String(p.id).replace(/'/g,'')}')">Adjust savings %</button>`;
      }
      return `
        <tr>
          <td>${p.id}</td>
          <td>${String(p.type || 'phi').toUpperCase()}</td>
          <td>$${Number(p.coverage_amount || 0).toLocaleString()}</td>
          <td>${money(monthly)} / mo</td>
          <td>${invPct}% savings</td>
          <td>${badge(status)}</td>
          <td>${actions}</td>
        </tr>
      `;
    });
  tbody.innerHTML = rows.join('');
}

window.__updateAllocation = async function __updateAllocation(policyId) {
  const pct = prompt('New savings percentage (0-99):');
  if (pct === null) return;
  const v = Number(pct);
  if (!Number.isFinite(v) || v < 0 || v > 99) {
    alert('Invalid value.');
    return;
  }
  try {
    const resp = await fetch('/api/policies/update-allocation', {
      method: 'POST',
      headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ policy_id: policyId, savings_percentage: v }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || !data.success) throw new Error(data.error || 'Update failed');
    alert('Updated. New premiums apply to next cycle.');
    const updatedPolicies = await loadPolicies();
    renderPolicies(updatedPolicies);
  } catch (e) {
    alert('Update failed.');
  }
};

function renderClaims(claims) {
  const tbody = document.getElementById('claims-table');
  if (!claims.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="color:var(--muted)">No claims yet.</td></tr>';
    return;
  }
  const rows = claims
    .sort((a, b) => String(b.filed_date || b.created_date || '').localeCompare(String(a.filed_date || a.created_date || '')))
    .slice(0, 100)
    .map(c => `
      <tr>
        <td>${c.id}</td>
        <td>${c.policy_id || '-'}</td>
        <td>${c.filed_date ? new Date(c.filed_date).toLocaleDateString() : '-'}</td>
        <td>${money(c.claimed_amount)}</td>
        <td>${badge(c.status || 'pending')}</td>
        <td><button class="btn-small" onclick="alert('Claim details coming soon')">Details</button></td>
      </tr>
    `);
  tbody.innerHTML = rows.join('');
}

function setupClaimModal(profile, policies) {
  const modal = document.getElementById('claim-modal');
  const openBtn = document.getElementById('open-claim-modal');
  const closeBtn = document.getElementById('close-claim-modal');
  const cancelBtn = document.getElementById('cancel-claim');
  const form = document.getElementById('claim-form');
  const msg = document.getElementById('claim-msg');
  const policySel = document.getElementById('claim-policy');

  if (!modal || !openBtn || !closeBtn || !cancelBtn || !form || !policySel) return;

  const eligible = (policies || []).filter(p => String(p.status || '').toLowerCase() !== 'rejected');
  policySel.innerHTML = eligible.length
    ? eligible.map(p => `<option value="${p.id}">${p.id} — ${String(p.type || '').toUpperCase()}</option>`).join('')
    : `<option value="">No policies available</option>`;

  function open() { modal.classList.add('active'); if (msg) msg.textContent = ''; }
  function close() { modal.classList.remove('active'); if (msg) msg.textContent = ''; }

  openBtn.addEventListener('click', open);
  closeBtn.addEventListener('click', close);
  cancelBtn.addEventListener('click', close);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (msg) msg.textContent = 'Submitting…';
    const payload = {
      customer_id: profile.customer_id,
      policy_id: policySel.value,
      type: document.getElementById('claim-type').value,
      claimed_amount: Number(document.getElementById('claim-amount').value),
      description: document.getElementById('claim-description').value,
    };
    try {
      const resp = await fetch('/api/claims/create', {
        method: 'POST',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || 'Failed to create claim');
      if (msg) msg.textContent = `Claim submitted: ${data.id}`;
      setTimeout(() => { close(); window.location.reload(); }, 700);
    } catch (err) {
      if (msg) msg.textContent = 'Error: ' + (err?.message || 'failed');
    }
  });
}

function renderStatement(stmt) {
  const summary = document.getElementById('summary');
  const allocations = Array.isArray(stmt.allocations) ? stmt.allocations : [];

  const riskPct = allocations.length ? allocations[allocations.length - 1].risk_percentage : null;
  const savingsPct = allocations.length ? allocations[allocations.length - 1].savings_percentage : null;

  summary.innerHTML = `
    <div class="summary-item">
      <div class="summary-label">Total Premium</div>
      <div class="summary-value">${money(stmt.total_premium)}</div>
    </div>
    <div class="summary-item">
      <div class="summary-label">Risk Allocation${riskPct != null ? ` (${riskPct}%)` : ''}</div>
      <div class="summary-value">${money(stmt.risk_total)}</div>
    </div>
    <div class="summary-item">
      <div class="summary-label">Savings Allocation${savingsPct != null ? ` (${savingsPct}%)` : ''}</div>
      <div class="summary-value">${money(stmt.savings_total)}</div>
    </div>
  `;

  const list = document.getElementById('alloc-list');
  if (!allocations.length) {
    list.innerHTML = '<li><span style="color:var(--muted)">No premium allocations yet (no successful payments recorded).</span></li>';
    return;
  }
  list.innerHTML = allocations
    .slice(-20)
    .reverse()
    .map(a => `
      <li>
        <span><strong>${a.allocation_id}</strong><br><span style="color:var(--muted); font-size:0.85rem">${a.timestamp ? new Date(a.timestamp).toLocaleString() : ''}</span></span>
        <span>Total: ${money(a.amount)} | Risk: ${money(a.risk_amount)} | Savings: ${money(a.savings_amount)}</span>
      </li>
    `)
    .join('');
}

function renderMarket(snapshot) {
  const el = document.getElementById('market-snapshot');
  // If the new chart widget is present, don't render the old snapshot block.
  if (document.getElementById('customer-market')) {
    return;
  }
  const crypto = snapshot.crypto || [];
  const indexes = snapshot.indexes || [];

  const parts = [];
  if (crypto.length) {
    parts.push('<div style="margin-bottom:8px"><strong>Crypto</strong></div>');
    parts.push('<div style="display:flex; flex-wrap:wrap; gap:12px; margin-bottom:12px;">' + crypto.map(q => `
      <div style="padding:10px 12px; border:1px solid var(--border); border-radius:10px; background:#fff;">
        <div style="font-weight:700">${q.symbol}</div>
        <div style="color:var(--muted)">${money(q.price)} <span style="font-size:0.85rem">(${q.currency})</span></div>
      </div>
    `).join('') + '</div>');
  }
  if (indexes.length) {
    parts.push('<div style="margin-bottom:8px"><strong>Indexes</strong></div>');
    parts.push('<div style="display:flex; flex-wrap:wrap; gap:12px;">' + indexes.map(q => `
      <div style="padding:10px 12px; border:1px solid var(--border); border-radius:10px; background:#fff;">
        <div style="font-weight:700">${q.symbol}</div>
        <div style="color:var(--muted)">${Number(q.price).toLocaleString(undefined, {maximumFractionDigits: 2})}</div>
      </div>
    `).join('') + '</div>');
  }

  el.innerHTML = parts.length ? parts.join('') : '<span style="color:var(--muted)">Market data unavailable.</span>';
}

function updateTopStats(policies, claims, statement, marketSnapshot) {
  const activePolicies = policies.filter(p => String(p.status || '').toLowerCase() === 'active');
  document.getElementById('policy-count').textContent = String(activePolicies.length);

  // Monthly premium total: sum of monthly premiums for active policies
  const totalMonthly = activePolicies.reduce((sum, p) => sum + Number(p.monthly_premium ?? (p.annual_premium ? Number(p.annual_premium) / 12 : 0) ?? 0), 0);
  document.getElementById('total-premium').textContent = money(totalMonthly);

  const openClaims = claims.filter(c => !['paid', 'rejected', 'closed'].includes(String(c.status || '').toLowerCase()));
  document.getElementById('claim-count').textContent = String(openClaims.length);

  // Investment value: use statement savings_total as proxy (demo); in production compute from portfolio valuation.
  const investmentValue = Number(statement.savings_total || 0);
  document.getElementById('investment-value').textContent = money(investmentValue);

  // Coverage details
  const coverageDetails = document.getElementById('coverage-details');
  const anyPhi = policies.find(p => ['disability', 'phi', 'phi_disability', 'permanent_disability'].includes(String(p.type || '').toLowerCase()));
  if (anyPhi) {
    const alloc = anyPhi.savings_percentage ?? 25;
    const load = anyPhi.operational_reinsurance_load ?? 50;
    coverageDetails.innerHTML = `<strong>Coverage Details:</strong> PHI Permanent Disability (ADL-based) with adjustable savings allocation (${alloc}% savings) and operational+reinsurance load (${load}%).`;
  } else {
    coverageDetails.innerHTML = `<strong>Coverage Details:</strong> Coverage and investment allocations will appear here once you have a PHI policy.`;
  }

  // Billing + portfolio cards
  document.getElementById('billing-balance').textContent = money(0);
  document.getElementById('billing-due-date').textContent = 'Due Date: -';

  const historyEl = document.getElementById('billing-history');
  const allocs = (statement.allocations || []).slice(-3).reverse();
  historyEl.innerHTML = allocs.length
    ? allocs.map(a => `<li><span>${a.timestamp ? new Date(a.timestamp).toLocaleDateString() : '-'}</span><span class="payment-amount">${money(a.amount)}</span></li>`).join('')
    : '<li><span style="color:var(--muted)">No payments yet</span><span></span></li>';

  document.getElementById('portfolio-total-value').textContent = money(investmentValue);
  document.getElementById('portfolio-contributions').textContent = money(investmentValue);
  document.getElementById('portfolio-returns').textContent = '<span class="muted-text">Valuation model coming next</span>';

  renderMarket(marketSnapshot);
}

function renderInvestmentAllocations(data) {
  const el = document.getElementById('investment-allocations');
  if (!el) return;
  const items = Array.isArray(data.items) ? data.items : [];
  if (!items.length) {
    el.innerHTML = '<span style="color:var(--muted)">No investment allocations yet (no savings premiums recorded).</span>';
    return;
  }
  const blocks = items.map((p) => {
    const basket = Array.isArray(p.basket) ? p.basket : [];
    const currency = p.currency || 'USD';
    const rows = basket.slice(0, 12).map((b) => {
      const pct = Math.round(Number(b.weight || 0) * 100);
      const amt = Number(b.amount || 0);
      return `
        <div style="display:flex; justify-content:space-between; gap:12px; padding:6px 0; border-bottom:1px solid var(--border)">
          <div><strong>${b.symbol}</strong> <span style="color:var(--muted); font-size:12px">${b.kind}</span></div>
          <div style="text-align:right">${pct}% — <strong>${money(amt)}</strong> <span style="color:var(--muted); font-size:12px">${currency}</span></div>
        </div>
      `;
    }).join('');
    return `
      <div class="card" style="margin-bottom:12px">
        <div style="display:flex; justify-content:space-between; flex-wrap:wrap; gap:10px">
          <div style="font-weight:900">Policy ${p.policy_id}</div>
          <div style="color:var(--muted)">Savings total: <strong>${money(p.savings_total)}</strong> • Risk total: <strong>${money(p.risk_total)}</strong></div>
        </div>
        <div style="margin-top:10px">${rows}</div>
      </div>
    `;
  }).join('');
  el.innerHTML = blocks;
}

async function loadSavingsProjectionForPolicy({ policy, age }) {
  const qs = new URLSearchParams();
  qs.set('type', String(policy.type || 'disability'));
  qs.set('coverage_amount', String(policy.coverage_amount || 100000));
  qs.set('age', String(age || 30));
  qs.set('jurisdiction', String(policy.jurisdiction || 'US'));
  qs.set('savings_percentage', String(policy.savings_percentage ?? 25));
  qs.set('operational_reinsurance_load', String(policy.operational_reinsurance_load ?? 50));
  qs.set('health_condition_score', String(policy.health_condition_score ?? 3));
  qs.set('years', String(policy.policy_term_years ?? 15));
  const resp = await fetch(`/api/projections/savings?${qs.toString()}`, { headers: getAuthHeaders() });
  return resp.json();
}

function renderSavingsProjections({ profile, policies }) {
  const el = document.getElementById('savings-projections');
  if (!el) return;
  const active = (policies || []).filter(p => String(p.status || '').toLowerCase() === 'active');
  if (!active.length) {
    el.innerHTML = '<span style="color:var(--muted)">No active policies yet.</span>';
    return;
  }
  const age = calcAgeFromDob(profile?.dob) || 30;
  el.textContent = 'Calculating…';
  Promise.all(active.slice(0, 20).map(p => loadSavingsProjectionForPolicy({ policy: p, age }).then(r => ({ policy: p, proj: r })).catch(() => ({ policy: p, proj: null }))))
    .then((rows) => {
      const blocks = rows.map(({ policy, proj }) => {
        if (!proj || proj.error) {
          return `<div class="card" style="margin-bottom:12px"><div style="font-weight:900">Policy ${policy.id}</div><div style="color:var(--muted); margin-top:6px">Projection unavailable.</div></div>`;
        }
        const p = Array.isArray(proj.projection) ? proj.projection : [];
        const monthlySav = Number(proj.monthly_savings_allocation || 0);
        const years = Number(proj.inputs?.years || policy.policy_term_years || 15);
        return `
          <div class="card" style="margin-bottom:12px">
            <div style="display:flex; justify-content:space-between; flex-wrap:wrap; gap:10px">
              <div style="font-weight:900">Policy ${policy.id}</div>
              <div style="color:var(--muted)">Term: ${years}y • Monthly savings: <strong>${money(monthlySav)}</strong></div>
            </div>
            <div style="display:flex; gap:12px; flex-wrap:wrap; margin-top:10px">
              ${p.map(x => `
                <div class="card" style="padding:10px 12px">
                  <div style="font-weight:800">${x.scenario}</div>
                  <div style="color:var(--muted); font-size:12px">${Number(x.annual_return_percent||0).toFixed(0)}%/yr</div>
                  <div style="margin-top:6px; font-weight:900">$${Number(x.future_value||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}</div>
                </div>
              `).join('')}
            </div>
          </div>
        `;
      }).join('');
      el.innerHTML = blocks;
    })
    .catch(() => {
      el.textContent = 'Projection unavailable.';
    });
}

// Language selector (kept compatible with existing UI)
window.changeLanguage = function changeLanguage(lang) {
  localStorage.setItem('phins_language', lang);
  const notification = document.createElement('div');
  notification.style.cssText = 'position:fixed;top:80px;right:20px;background:#28a745;color:#fff;padding:16px 24px;border-radius:8px;box-shadow:0 4px 12px rgba(0,0,0,0.2);z-index:1000;font-weight:600;';
  notification.textContent = 'Language changed to ' + document.getElementById('language-selector').selectedOptions[0].text;
  document.body.appendChild(notification);
  setTimeout(() => notification.remove(), 3000);
};

document.addEventListener('DOMContentLoaded', async () => {
  const token = getToken();
  if (!token) {
    window.location.href = '/login.html';
    return;
  }

  const savedLang = localStorage.getItem('phins_language');
  if (savedLang && document.getElementById('language-selector')) {
    document.getElementById('language-selector').value = savedLang;
  }

  // Logout button
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

  try {
    const profile = await loadProfile();
    if (!profile) return;
    const username = sessionStorage.getItem('username') || profile.username || 'Customer';
    document.getElementById('username').textContent = username;

    const [policies, claims, apps, statement, market, notifs, invAllocs, wallet] = await Promise.all([
      loadPolicies(),
      loadClaims(),
      loadApplications(),
      loadStatement(),
      loadMarketSnapshot(),
      loadNotifications(),
      loadInvestmentAllocations(),
      loadWalletBalance(),
    ]);

    renderApplications(apps);
    renderNotifications(notifs);
    renderPolicies(policies);
    renderClaims(claims);
    renderStatement(statement);
    renderInvestmentAllocations(invAllocs);
    updateTopStats(policies, claims, statement, market);
    setupClaimModal(profile, policies);
    renderSavingsProjections({ profile, policies });

    // Deposit / invest UI
    try {
      const sel = document.getElementById('deposit-policy');
      const amt = document.getElementById('deposit-amount');
      const btn = document.getElementById('deposit-btn');
      const msg = document.getElementById('deposit-msg');
      const balEl = document.getElementById('wallet-balance');
      if (balEl && wallet && typeof wallet.balance !== 'undefined') {
        balEl.textContent = money(wallet.balance);
      }
      if (sel) {
        const eligible = (policies || []).filter(p => ['active', 'billing_pending', 'billing_review'].includes(String(p.status || '').toLowerCase()));
        sel.innerHTML = eligible.length
          ? eligible.map(p => `<option value="${p.id}">${p.id} — ${String(p.type || '').toUpperCase()} (${String(p.status || '')})</option>`).join('')
          : `<option value="">No eligible policies</option>`;
      }
      if (btn) {
        btn.addEventListener('click', async () => {
          const policy_id = String(sel?.value || '').trim();
          const amount = Number(amt?.value || 0);
          if (!policy_id) { msg && (msg.textContent = 'Select a policy.'); return; }
          if (!(amount > 0)) { msg && (msg.textContent = 'Enter a valid amount.'); return; }
          msg && (msg.textContent = 'Depositing…');
          try {
            const res = await depositToWallet({ policy_id, amount });
            msg && (msg.textContent = 'Deposit recorded.');
            if (balEl) balEl.textContent = money(res.balance || 0);
            // refresh policy list to reflect embedded savings (best-effort)
            const updatedPolicies = await loadPolicies();
            renderPolicies(updatedPolicies);
          } catch (e) {
            msg && (msg.textContent = 'Deposit failed.');
          }
        });
      }
    } catch (_) {}

    // Market charts (adjustable, best-effort realtime)
    try {
      if (typeof renderMarketCharts === 'function') {
        await renderMarketCharts('customer-market', { storeKeyCrypto: 'phins_customer_crypto', storeKeyIndex: 'phins_customer_index', intervalSeconds: 30 });
      }
    } catch (e) {
      console.error(e);
    }
  } catch (err) {
    console.error('Dashboard load error:', err);
    alert('Failed to load dashboard. Please try again.');
  }
});

