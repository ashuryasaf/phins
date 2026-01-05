function getToken() {
  return localStorage.getItem('phins_token');
}

async function apiGet(path) {
  const token = getToken();
  const r = await fetch(path, {
    headers: token ? { 'Authorization': `Bearer ${token}` } : {}
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

async function apiPost(path, payload) {
  const token = getToken();
  const r = await fetch(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { 'Authorization': `Bearer ${token}` } : {})
    },
    body: JSON.stringify(payload || {})
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

async function loadSession() {
  const who = document.getElementById('whoami');
  const token = getToken();
  if (!token) {
    who.textContent = 'Not logged in. Please login.';
    return null;
  }
  try {
    const s = await apiGet('/api/session/validate');
    who.textContent = `Signed in as ${s.username || 'unknown'} (${s.role || 'unknown'})`;
    return s;
  } catch (e) {
    who.textContent = 'Session invalid. Please login.';
    return null;
  }
}

function esc(x) {
  return String(x == null ? '' : x)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

async function refreshTables() {
  const body = document.getElementById('tables-body');
  body.innerHTML = `<tr><td colspan="7" class="muted-text">Loading...</td></tr>`;
  try {
    const data = await apiGet('/api/admin/actuarial-tables');
    const items = data.items || [];
    if (!items.length) {
      body.innerHTML = `<tr><td colspan="7" class="muted-text">No actuarial tables found.</td></tr>`;
      return;
    }
    body.innerHTML = items.map(t => `
      <tr>
        <td>${esc(t.id)}</td>
        <td>${esc(t.name)}</td>
        <td>${esc(t.table_type)}</td>
        <td>${esc(t.version)}</td>
        <td>${esc(t.effective_date || '')}</td>
        <td>${esc(t.created_by || '')}</td>
        <td>${esc(t.created_date || t.created_at || '')}</td>
      </tr>
    `).join('');
  } catch (e) {
    body.innerHTML = `<tr><td colspan="7" class="text-danger">Failed: ${esc(e.message)}</td></tr>`;
  }
}

async function uploadTable() {
  const msg = document.getElementById('upload-msg');
  msg.textContent = 'Uploading...';
  msg.className = 'muted-text';
  const raw = document.getElementById('actuarial-json').value || '';
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch (e) {
    msg.textContent = 'Invalid JSON.';
    msg.className = 'text-danger';
    return;
  }
  try {
    const res = await apiPost('/api/admin/actuarial-tables/upload', payload);
    msg.textContent = `Uploaded: ${res.id || 'ok'}`;
    msg.className = 'text-success';
    await refreshTables();
  } catch (e) {
    msg.textContent = `Upload failed: ${e.message}`;
    msg.className = 'text-danger';
  }
}

function statusBadge(status) {
  const s = (status || '').toLowerCase();
  if (s === 'approved') return `<span class="badge badge-success">approved</span>`;
  if (s === 'draft') return `<span class="badge badge-pending">draft</span>`;
  return `<span class="badge badge-inactive">${esc(status || 'unknown')}</span>`;
}

async function refreshFeeSchedules() {
  const body = document.getElementById('fees-body');
  body.innerHTML = `<tr><td colspan="8" class="muted-text">Loading...</td></tr>`;
  try {
    const data = await apiGet('/api/admin/fee-schedules');
    const items = data.items || [];
    if (!items.length) {
      body.innerHTML = `<tr><td colspan="8" class="muted-text">No fee schedules yet.</td></tr>`;
      return;
    }
    body.innerHTML = items.map(fs => `
      <tr>
        <td>${esc(fs.id)}</td>
        <td>${esc(fs.domain)}</td>
        <td>${esc(fs.version)}</td>
        <td>${esc(fs.effective_date)}</td>
        <td>${statusBadge(fs.status)}</td>
        <td>${esc(fs.created_by || '')}</td>
        <td>${esc(fs.approved_by || '')}</td>
        <td>
          ${(String(fs.status).toLowerCase() === 'draft')
            ? `<button class="btn-small btn-success" data-approve="${esc(fs.id)}">Approve</button>`
            : `<span class="muted-text">—</span>`}
        </td>
      </tr>
    `).join('');

    body.querySelectorAll('button[data-approve]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-approve');
        const notes = prompt('Approval notes (optional):') || '';
        try {
          await apiPost('/api/admin/fee-schedules/approve', { id, approval_notes: notes });
          await refreshFeeSchedules();
        } catch (e) {
          alert(`Approve failed: ${e.message}`);
        }
      });
    });
  } catch (e) {
    body.innerHTML = `<tr><td colspan="8" class="text-danger">Failed: ${esc(e.message)}</td></tr>`;
  }
}

async function createFeeSchedule() {
  const msg = document.getElementById('fee-msg');
  msg.textContent = 'Creating...';
  msg.className = 'muted-text';

  const domain = (document.getElementById('fee-domain').value || '').trim();
  const version = (document.getElementById('fee-version').value || '').trim();
  const effective_date = (document.getElementById('fee-effective').value || '').trim();
  const rulesRaw = document.getElementById('fee-rules').value || '';
  let rules;
  try {
    rules = JSON.parse(rulesRaw);
  } catch (e) {
    msg.textContent = 'Rules JSON is invalid.';
    msg.className = 'text-danger';
    return;
  }

  try {
    const res = await apiPost('/api/admin/fee-schedules/create', {
      domain,
      version: version || undefined,
      effective_date: effective_date || undefined,
      rules
    });
    msg.textContent = `Draft created: ${res.id}`;
    msg.className = 'text-success';
    await refreshFeeSchedules();
  } catch (e) {
    msg.textContent = `Create failed: ${e.message}`;
    msg.className = 'text-danger';
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  await loadSession();
  await refreshTables();
  await refreshFeeSchedules();

  document.getElementById('refresh-tables').addEventListener('click', refreshTables);
  document.getElementById('upload-table').addEventListener('click', uploadTable);
  document.getElementById('refresh-fees').addEventListener('click', refreshFeeSchedules);
  document.getElementById('create-fee').addEventListener('click', createFeeSchedule);
});

