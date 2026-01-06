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

async function uploadFile() {
  const msg = document.getElementById('upload-file-msg');
  msg.textContent = 'Uploading file...';
  msg.className = 'muted-text';

  const fileInput = document.getElementById('actuarial-file');
  const file = fileInput.files && fileInput.files[0];
  if (!file) {
    msg.textContent = 'Please select a file.';
    msg.className = 'text-danger';
    return;
  }

  const name = (document.getElementById('upload-name').value || '').trim();
  const table_type = (document.getElementById('upload-table-type').value || '').trim();
  const version = (document.getElementById('upload-version').value || '').trim();
  const effective_date = (document.getElementById('upload-effective').value || '').trim();
  const sheet = (document.getElementById('upload-sheet').value || '').trim();

  const token = getToken();
  if (!token) {
    msg.textContent = 'Not logged in.';
    msg.className = 'text-danger';
    return;
  }

  const fd = new FormData();
  fd.append('file', file, file.name);
  if (name) fd.append('name', name);
  if (table_type) fd.append('table_type', table_type);
  if (version) fd.append('version', version);
  if (effective_date) fd.append('effective_date', effective_date);
  if (sheet) fd.append('sheet', sheet);

  try {
    const r = await fetch('/api/admin/actuarial-tables/upload-file', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` },
      body: fd
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    msg.textContent = `Uploaded: ${data.id || 'ok'}`;
    msg.className = 'text-success';
    fileInput.value = '';
    await refreshTables();
  } catch (e) {
    msg.textContent = `Upload failed: ${e.message}`;
    msg.className = 'text-danger';
  }
}

async function refreshBi() {
  const pre = document.getElementById('bi-json');
  pre.textContent = 'Loading...';
  try {
    const data = await apiGet('/api/bi/actuary');
    pre.textContent = JSON.stringify(data, null, 2);
    pre.className = 'muted-text';
  } catch (e) {
    pre.textContent = `Failed: ${e.message}`;
    pre.className = 'text-danger';
  }
}

function getReinsInputs() {
  const total_exposure = (document.getElementById('reins-total-exposure').value || '').trim();
  const expected_loss_ratio = (document.getElementById('reins-loss-ratio').value || '').trim();
  const risk_band = (document.getElementById('reins-risk-band').value || 'medium').trim().toLowerCase();
  const region = (document.getElementById('reins-region').value || 'global').trim();
  const line_of_business = (document.getElementById('reins-lob').value || 'health').trim().toLowerCase();
  const currency = (document.getElementById('reins-currency').value || 'USD').trim().toUpperCase();
  const objective = (document.getElementById('reins-objective').value || 'min_cost').trim();
  const contract_name = (document.getElementById('reins-contract-name').value || 'Reinsurance Contract').trim();
  const portfolio_id = (document.getElementById('reins-portfolio-id').value || '').trim();

  return {
    total_exposure,
    expected_loss_ratio,
    risk_band,
    region,
    line_of_business,
    currency,
    objective,
    contract_name,
    portfolio_id: portfolio_id || undefined,
  };
}

function setReinsMsg(text, cls) {
  const msg = document.getElementById('reins-msg');
  msg.textContent = text || '';
  msg.className = cls || 'muted-text';
}

function getConfidence(q) {
  try {
    return q && q.terms ? q.terms.confidence : '';
  } catch {
    return '';
  }
}

let _lastQuotes = [];
let _recommended = null;

async function refreshReinsProviders() {
  const el = document.getElementById('reins-providers');
  el.textContent = 'Loading...';
  try {
    const data = await apiGet('/api/reinsurance/providers');
    const items = data.items || [];
    if (!items.length) {
      el.textContent = 'No providers available.';
      return;
    }
    el.textContent = items.map(p => `${p.name}${p.configured ? '' : ' (not configured)'}`).join(', ');
  } catch (e) {
    el.textContent = `Failed: ${e.message}`;
  }
}

function renderQuotes(items) {
  const body = document.getElementById('reins-quotes-body');
  if (!items || !items.length) {
    body.innerHTML = `<tr><td colspan="8" class="muted-text">No quotes returned.</td></tr>`;
    return;
  }
  body.innerHTML = items.map(q => `
    <tr>
      <td>${esc(q.quote_id)}</td>
      <td>${esc(q.provider)}</td>
      <td>${esc(q.product)}</td>
      <td>${esc(q.currency)} ${esc(q.annual_premium)}</td>
      <td>${esc(q.attachment_point)}</td>
      <td>${esc(q.limit)}</td>
      <td>${esc(q.ceded_share_pct)}</td>
      <td>${esc(getConfidence(q))}</td>
    </tr>
  `).join('');
}

async function runReinsQuotes() {
  setReinsMsg('Running quotes...', 'muted-text');
  _recommended = null;
  document.getElementById('reins-bind').disabled = true;

  const inp = getReinsInputs();
  const qs = new URLSearchParams({
    currency: inp.currency,
    total_exposure: inp.total_exposure || '0',
    expected_loss_ratio: inp.expected_loss_ratio || '0.6',
    risk_band: inp.risk_band || 'medium',
    region: inp.region || 'global',
    line_of_business: inp.line_of_business || 'health',
  }).toString();

  try {
    const data = await apiGet(`/api/reinsurance/quote?${qs}`);
    _lastQuotes = data.items || [];
    renderQuotes(_lastQuotes);
    setReinsMsg(`Quotes: ${_lastQuotes.length}`, 'text-success');
  } catch (e) {
    _lastQuotes = [];
    renderQuotes([]);
    setReinsMsg(`Quote failed: ${e.message}`, 'text-danger');
  }
}

async function recommendReins() {
  setReinsMsg('Computing recommendation...', 'muted-text');
  document.getElementById('reins-bind').disabled = true;
  _recommended = null;

  const inp = getReinsInputs();
  const qs = new URLSearchParams({
    objective: inp.objective,
    currency: inp.currency,
    total_exposure: inp.total_exposure || '0',
    expected_loss_ratio: inp.expected_loss_ratio || '0.6',
    risk_band: inp.risk_band || 'medium',
    region: inp.region || 'global',
    line_of_business: inp.line_of_business || 'health',
  }).toString();

  try {
    const data = await apiGet(`/api/reinsurance/recommendation?${qs}`);
    _lastQuotes = data.quotes || [];
    _recommended = data.recommended || null;
    renderQuotes(_lastQuotes);
    if (_recommended) {
      setReinsMsg(`Recommended: ${_recommended.provider} (${_recommended.product})`, 'text-success');
      document.getElementById('reins-bind').disabled = false;
    } else {
      setReinsMsg('No recommendation returned.', 'text-danger');
    }
  } catch (e) {
    setReinsMsg(`Recommendation failed: ${e.message}`, 'text-danger');
  }
}

async function bindRecommended() {
  if (!_recommended) {
    setReinsMsg('No recommended quote to bind.', 'text-danger');
    return;
  }
  const inp = getReinsInputs();
  setReinsMsg('Binding contract...', 'muted-text');
  try {
    const res = await apiPost('/api/reinsurance/contracts/bind', {
      contract_name: inp.contract_name || 'Reinsurance Contract',
      portfolio_id: inp.portfolio_id,
      quote: _recommended
    });
    setReinsMsg(`Bound contract: ${res.id}`, 'text-success');
    await refreshContracts();
  } catch (e) {
    setReinsMsg(`Bind failed: ${e.message}`, 'text-danger');
  }
}

async function refreshContracts() {
  const body = document.getElementById('reins-contracts-body');
  body.innerHTML = `<tr><td colspan="8" class="muted-text">Loading...</td></tr>`;
  try {
    const data = await apiGet('/api/reinsurance/contracts');
    const items = data.items || [];
    if (!items.length) {
      body.innerHTML = `<tr><td colspan="8" class="muted-text">No contracts yet.</td></tr>`;
      return;
    }
    body.innerHTML = items.map(c => `
      <tr>
        <td>${esc(c.id)}</td>
        <td>${esc(c.name)}</td>
        <td>${esc(c.provider)}</td>
        <td>${esc(c.product)}</td>
        <td>${esc(c.currency)}</td>
        <td>${esc(c.annual_premium)}</td>
        <td>${esc(c.status)}</td>
        <td>${esc(c.created_at)}</td>
      </tr>
    `).join('');
  } catch (e) {
    body.innerHTML = `<tr><td colspan="8" class="text-danger">Failed: ${esc(e.message)}</td></tr>`;
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  await loadSession();
  await refreshTables();
  await refreshFeeSchedules();
  await refreshBi();
  await refreshReinsProviders();
  await refreshContracts();

  document.getElementById('refresh-tables').addEventListener('click', refreshTables);
  document.getElementById('upload-table').addEventListener('click', uploadTable);
  document.getElementById('upload-file').addEventListener('click', uploadFile);
  document.getElementById('refresh-fees').addEventListener('click', refreshFeeSchedules);
  document.getElementById('create-fee').addEventListener('click', createFeeSchedule);
  document.getElementById('refresh-bi').addEventListener('click', refreshBi);
  document.getElementById('refresh-reins').addEventListener('click', async () => {
    await refreshReinsProviders();
    await refreshContracts();
  });
  document.getElementById('reins-run-quotes').addEventListener('click', runReinsQuotes);
  document.getElementById('reins-recommend').addEventListener('click', recommendReins);
  document.getElementById('reins-bind').addEventListener('click', bindRecommended);
  document.getElementById('reins-refresh-contracts').addEventListener('click', refreshContracts);
});

