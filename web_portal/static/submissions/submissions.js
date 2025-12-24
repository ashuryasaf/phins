function getToken() {
  return localStorage.getItem('phins_token') || localStorage.getItem('phins_admin_token');
}

function getAuthHeaders() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

async function loadProfile() {
  const resp = await fetch('/api/profile', { headers: getAuthHeaders() });
  if (resp.status === 401) return null;
  return resp.json();
}

async function fetchSubmissions({ email, source }) {
  const u = new URL(window.location.href);
  const qs = new URLSearchParams();
  if (email) qs.set('email', email);
  if (source) qs.set('source', source);
  const resp = await fetch(`/api/submissions?${qs.toString()}`, { headers: getAuthHeaders() });
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || 'Failed to load submissions');
  return Array.isArray(data.items) ? data.items : [];
}

function render(items) {
  const tbody = document.getElementById('subs-table');
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="color:var(--muted)">No submissions found.</td></tr>';
    return;
  }
  tbody.innerHTML = items.slice(0, 200).map(s => {
    const created = s.created_date ? new Date(s.created_date).toLocaleString() : '-';
    const payload = esc(s.payload || '').slice(0, 1600);
    return `
      <tr>
        <td>${esc(s.id)}</td>
        <td>${esc(created)}</td>
        <td>${esc(s.source)}</td>
        <td>${esc(s.email || '')}</td>
        <td>${esc(s.customer_id || '')}</td>
        <td><pre style="white-space:pre-wrap; max-width:520px; margin:0">${payload}</pre></td>
      </tr>
    `;
  }).join('');
}

document.addEventListener('DOMContentLoaded', async () => {
  const prof = await loadProfile();
  if (!prof) {
    window.location.href = '/login.html';
    return;
  }

  const emailEl = document.getElementById('email-filter');
  const sourceEl = document.getElementById('source-filter');
  const refreshBtn = document.getElementById('refresh-btn');

  // Customers cannot filter by email (server will ignore anyway)
  if (String(prof.role || '').toLowerCase() === 'customer') {
    emailEl.disabled = true;
    emailEl.placeholder = 'Customer view';
  }

  async function refresh() {
    const email = emailEl.value.trim();
    const source = sourceEl.value.trim();
    const items = await fetchSubmissions({ email, source });
    render(items);
  }

  refreshBtn.addEventListener('click', refresh);
  await refresh();
});

