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

function esc(x) {
  return String(x == null ? '' : x)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
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

function badgeActive(active) {
  return active
    ? `<span class="badge badge-active">active</span>`
    : `<span class="badge badge-inactive">inactive</span>`;
}

async function refreshOffers() {
  const tbody = document.getElementById('offers-body');
  tbody.innerHTML = `<tr><td colspan="9" class="muted-text">Loading...</td></tr>`;
  try {
    const supplierId = (document.getElementById('supplier-id').value || '').trim();
    const qs = supplierId ? `?supplier_id=${encodeURIComponent(supplierId)}` : '';
    const data = await apiGet(`/api/supplier/offers${qs}`);
    const items = data.items || [];
    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="9" class="muted-text">No offers yet.</td></tr>`;
      return;
    }
    tbody.innerHTML = items.map(o => `
      <tr>
        <td>${esc(o.id)}</td>
        <td>${esc(o.supplier_id)}</td>
        <td>${esc(o.item_type)}</td>
        <td>${esc(o.category)}</td>
        <td>${esc(o.name)}</td>
        <td>${esc(o.currency)} ${esc(o.price)}</td>
        <td>${badgeActive(!!o.active)}</td>
        <td>${esc(o.updated_at || o.created_at || '')}</td>
        <td style="white-space:nowrap">
          <button class="btn-small" data-edit="${esc(o.id)}">Edit</button>
          <button class="btn-small btn-danger" data-del="${esc(o.id)}">Delete</button>
        </td>
      </tr>
    `).join('');

    tbody.querySelectorAll('button[data-edit]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-edit');
        const priceRaw = prompt('New price:');
        if (priceRaw == null) return;
        const price = parseFloat(priceRaw);
        if (!Number.isFinite(price) || price < 0) {
          alert('Invalid price');
          return;
        }
        const active = confirm('Set active? OK=yes, Cancel=no');
        // Load existing offer from table row quickly via current list
        const offer = (items || []).find(x => x.id === id);
        if (!offer) return;
        try {
          await apiPost('/api/supplier/offers/upsert', {
            id: offer.id,
            supplier_id: offer.supplier_id,
            category: offer.category,
            name: offer.name,
            item_type: offer.item_type,
            currency: offer.currency,
            price,
            active
          });
          await refreshOffers();
        } catch (e) {
          alert(`Update failed: ${e.message}`);
        }
      });
    });

    tbody.querySelectorAll('button[data-del]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-del');
        if (!confirm(`Delete offer ${id}?`)) return;
        try {
          await apiPost('/api/supplier/offers/delete', { id });
          await refreshOffers();
        } catch (e) {
          alert(`Delete failed: ${e.message}`);
        }
      });
    });
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="9" class="text-danger">Failed: ${esc(e.message)}</td></tr>`;
  }
}

async function createOffer() {
  const msg = document.getElementById('offer-msg');
  msg.textContent = 'Creating...';
  msg.className = 'muted-text';
  const supplier_id = (document.getElementById('supplier-id').value || '').trim();
  const category = (document.getElementById('offer-category').value || '').trim();
  const name = (document.getElementById('offer-name').value || '').trim();
  const price = parseFloat((document.getElementById('offer-price').value || '').trim());
  const currency = (document.getElementById('offer-currency').value || 'USD').trim();
  const item_type = (document.getElementById('offer-type').value || 'service').trim();
  const active = (document.getElementById('offer-active').value || 'true') === 'true';

  if (!category || !name || !Number.isFinite(price)) {
    msg.textContent = 'Missing category/name/price.';
    msg.className = 'text-danger';
    return;
  }

  try {
    const res = await apiPost('/api/supplier/offers/upsert', {
      supplier_id: supplier_id || undefined,
      category,
      name,
      item_type,
      price,
      currency,
      active
    });
    msg.textContent = `Created: ${res.id}`;
    msg.className = 'text-success';
    await refreshOffers();
  } catch (e) {
    msg.textContent = `Create failed: ${e.message}`;
    msg.className = 'text-danger';
  }
}

function statusBadge(status) {
  const s = (status || '').toLowerCase();
  if (['approved', 'completed', 'delivered', 'processing'].includes(s)) return `<span class="badge badge-success">${esc(s)}</span>`;
  if (['pending', 'pending_approval'].includes(s)) return `<span class="badge badge-pending">${esc(s)}</span>`;
  if (['cancelled', 'rejected', 'refunded'].includes(s)) return `<span class="badge badge-inactive">${esc(s)}</span>`;
  return `<span class="badge">${esc(status || 'unknown')}</span>`;
}

async function refreshOrders() {
  const tbody = document.getElementById('orders-body');
  tbody.innerHTML = `<tr><td colspan="9" class="muted-text">Loading...</td></tr>`;
  try {
    const supplierId = (document.getElementById('supplier-id').value || '').trim();
    const qs = supplierId ? `?supplier_id=${encodeURIComponent(supplierId)}&limit=50` : '?limit=50';
    const data = await apiGet(`/api/supplier/orders${qs}`);
    const items = data.items || [];
    if (!items.length) {
      tbody.innerHTML = `<tr><td colspan="9" class="muted-text">No orders found.</td></tr>`;
      return;
    }
    tbody.innerHTML = items.map(t => `
      <tr>
        <td>${esc(t.transaction_id)}</td>
        <td>${esc(t.supplier_id || '')}</td>
        <td>${esc(t.customer_id || '')}</td>
        <td>${esc(t.transaction_type || t.item_type || '')}</td>
        <td>${esc(t.item_name || t.item_id || '')}</td>
        <td>${esc(t.total_amount || '')}</td>
        <td>${statusBadge(t.status)}</td>
        <td>${esc(t.updated_at || t.created_at || '')}</td>
        <td style="white-space:nowrap">
          <button class="btn-small" data-status="${esc(t.transaction_id)}" data-val="processing">processing</button>
          <button class="btn-small btn-success" data-status="${esc(t.transaction_id)}" data-val="completed">completed</button>
          <button class="btn-small btn-success" data-status="${esc(t.transaction_id)}" data-val="delivered">delivered</button>
        </td>
      </tr>
    `).join('');

    tbody.querySelectorAll('button[data-status]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const transaction_id = btn.getAttribute('data-status');
        const status = btn.getAttribute('data-val');
        try {
          await apiPost('/api/supplier/orders/update-status', { transaction_id, status });
          await refreshOrders();
        } catch (e) {
          alert(`Update failed: ${e.message}`);
        }
      });
    });
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="9" class="text-danger">Failed: ${esc(e.message)}</td></tr>`;
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  await loadSession();
  await refreshOffers();
  await refreshOrders();

  document.getElementById('refresh-offers').addEventListener('click', refreshOffers);
  document.getElementById('create-offer').addEventListener('click', createOffer);
  document.getElementById('refresh-orders').addEventListener('click', refreshOrders);
});

