function qs(name) {
  const u = new URL(window.location.href);
  return u.searchParams.get(name);
}

function money(x) {
  const n = Number(x || 0);
  return '$' + n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

async function loadBill(token) {
  const resp = await fetch(`/api/billing/link?token=${encodeURIComponent(token)}`);
  const data = await resp.json();
  if (!resp.ok || !data.valid) {
    return { ok: false, error: data.error || 'Invalid or expired link' };
  }
  return { ok: true, data };
}

async function pay(token) {
  const resp = await fetch('/api/billing/link/pay', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  });
  const data = await resp.json();
  if (!resp.ok) {
    return { ok: false, error: data.error || 'Payment failed' };
  }
  return { ok: true, data };
}

document.addEventListener('DOMContentLoaded', async () => {
  const token = qs('token');
  const billBlock = document.getElementById('bill-block');
  const btn = document.getElementById('pay-btn');
  const msg = document.getElementById('msg');

  if (!token) {
    billBlock.textContent = 'Missing billing token.';
    return;
  }

  const loaded = await loadBill(token);
  if (!loaded.ok) {
    billBlock.textContent = loaded.error;
    return;
  }

  const bill = loaded.data.bill || {};
  const amount = bill.amount ?? bill.amount_due ?? 0;
  const status = bill.status || 'outstanding';
  billBlock.innerHTML = `
    <div><strong>Bill</strong>: ${bill.id || bill.bill_id || '-'}</div>
    <div><strong>Status</strong>: ${status}</div>
    <div><strong>Amount due</strong>: ${money(amount)}</div>
  `;

  btn.disabled = status === 'paid';
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    msg.textContent = 'Processing payment…';
    const res = await pay(token);
    if (!res.ok) {
      msg.textContent = res.error;
      btn.disabled = false;
      return;
    }
    msg.textContent = 'Payment completed. Thank you!';
  });
});

