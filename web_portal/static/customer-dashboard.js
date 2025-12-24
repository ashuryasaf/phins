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

function badge(status) {
  const s = String(status || '').toLowerCase();
  const cls = s.includes('active') || s === 'active' ? 'badge badge-active'
    : (s.includes('pending') || s === 'pending' ? 'badge badge-pending' : 'badge badge-inactive');
  return `<span class="${cls}">${String(status || 'unknown')}</span>`;
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

async function loadMarketSnapshot() {
  const [crypto, indexes] = await Promise.all([
    fetch('/api/market/crypto?symbols=BTC,ETH&vs=USD', { headers: getAuthHeaders() }).then(r => r.json()),
    fetch('/api/market/indexes?symbols=SPX,NASDAQ,DOW,FTSE&currency=USD', { headers: getAuthHeaders() }).then(r => r.json()),
  ]);
  return { crypto: crypto.items || [], indexes: indexes.items || [] };
}

function renderApplications(apps) {
  const tbody = document.getElementById('applications-table');
  if (!apps.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="color:var(--muted)">No applications in pipeline.</td></tr>';
    return;
  }
  const rows = apps
    .sort((a, b) => String(b.submitted_date || '').localeCompare(String(a.submitted_date || '')))
    .slice(0, 50)
    .map(a => `
      <tr>
        <td>${a.id || '-'}</td>
        <td>${a.policy_id || '-'}</td>
        <td>${badge(a.status || 'pending')}</td>
        <td>${a.risk_assessment ? badge(a.risk_assessment) : '-'}</td>
        <td>${a.submitted_date ? new Date(a.submitted_date).toLocaleDateString() : '-'}</td>
      </tr>
    `);
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
      return `
        <tr>
          <td>${p.id}</td>
          <td>${String(p.type || 'phi').toUpperCase()}</td>
          <td>$${Number(p.coverage_amount || 0).toLocaleString()}</td>
          <td>${money(monthly)} / mo</td>
          <td>${invPct}% savings</td>
          <td>${badge(status)}</td>
          <td><span style="color:var(--muted)">${jurisdiction}</span></td>
        </tr>
      `;
    });
  tbody.innerHTML = rows.join('');
}

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
      window.location.href = '/';
    });
  }

  try {
    const profile = await loadProfile();
    if (!profile) return;
    const username = sessionStorage.getItem('username') || profile.username || 'Customer';
    document.getElementById('username').textContent = username;

    const [policies, claims, apps, statement, market, notifs] = await Promise.all([
      loadPolicies(),
      loadClaims(),
      loadApplications(),
      loadStatement(),
      loadMarketSnapshot(),
      loadNotifications(),
    ]);

    renderApplications(apps);
    renderNotifications(notifs);
    renderPolicies(policies);
    renderClaims(claims);
    renderStatement(statement);
    updateTopStats(policies, claims, statement, market);
    setupClaimModal(profile, policies);

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

