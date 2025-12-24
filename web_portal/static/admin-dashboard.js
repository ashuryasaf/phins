// Admin dashboard: real data only (no fake seeded rows)

function getToken() {
  return localStorage.getItem('phins_token') || localStorage.getItem('phins_admin_token');
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

async function requireAdmin() {
  const token = getToken();
  if (!token) {
    window.location.href = '/login.html';
    return null;
  }
  const prof = await fetch('/api/profile', { headers: getAuthHeaders() }).then(r => r.json());
  if (!prof || !['admin'].includes(String(prof.role || '').toLowerCase())) {
    alert('Admin access required.');
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
}

async function loadPipeline() {
  const data = await fetch('/api/underwriting', { headers: getAuthHeaders() }).then(r => r.json());
  const items = Array.isArray(data.items) ? data.items : [];
  const tbody = document.getElementById('uw-table');
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="color:var(--muted)">No underwriting applications yet.</td></tr>';
    return;
  }
  const rows = items
    .sort((a, b) => String(b.submitted_date || '').localeCompare(String(a.submitted_date || '')))
    .slice(0, 50)
    .map(u => `
      <tr>
        <td>${u.id || '-'}</td>
        <td>${u.policy_id || '-'}</td>
        <td>${u.customer_id || '-'}</td>
        <td>${badge(u.status || 'pending')}</td>
        <td>${u.risk_assessment ? badge(u.risk_assessment) : '-'}</td>
        <td>${u.submitted_date ? new Date(u.submitted_date).toLocaleString() : '-'}</td>
      </tr>
    `);
  tbody.innerHTML = rows.join('');
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

  document.getElementById('actuarial-refresh').addEventListener('click', loadActuarialTable);
  document.getElementById('actuarial-jurisdiction').addEventListener('change', loadActuarialTable);

  try {
    await Promise.all([loadMetrics(), loadPipeline(), loadActuarialTable(), loadMarket()]);
  } catch (e) {
    console.error(e);
  }
});

