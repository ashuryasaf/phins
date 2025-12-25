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

async function acceptTerms(token, signer_name, signature_data_url) {
  const resp = await fetch('/api/billing/link/accept', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, signer_name, signature_data_url }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok || !data.success) {
    return { ok: false, error: data.error || 'Acceptance failed' };
  }
  return { ok: true, data };
}

document.addEventListener('DOMContentLoaded', async () => {
  const token = qs('token');
  const billBlock = document.getElementById('bill-block');
  const termsBlock = document.getElementById('terms-block');
  const openSign = document.getElementById('open-sign');
  const acceptStatus = document.getElementById('accept-status');
  const signModal = document.getElementById('signModal');
  const closeSign = document.getElementById('close-sign');
  const sigCanvas = document.getElementById('sigCanvas');
  const sigName = document.getElementById('sigName');
  const sigClear = document.getElementById('sigClear');
  const sigSubmit = document.getElementById('sigSubmit');
  const sigMsg = document.getElementById('sigMsg');
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
  const meta = loaded.data.meta || {};
  const nft = meta.nft_token || '';
  const termsUrl = meta.policy_terms_url || '';
  let acceptedServer = !!meta.terms_accepted;
  billBlock.innerHTML = `
    <div><strong>Bill</strong>: ${bill.id || bill.bill_id || '-'}</div>
    <div><strong>Status</strong>: ${status}</div>
    <div><strong>Amount due</strong>: ${money(amount)}</div>
  `;

  if (termsBlock) {
    const tLink = termsUrl ? `<a class="link" href="${termsUrl}" target="_blank" rel="noopener">Download policy terms (PDF)</a>` : '<span>Policy terms PDF not available yet.</span>';
    termsBlock.innerHTML = `
      <div>${tLink}</div>
      ${nft ? `<div style="margin-top:6px">NFT policy ledger token: <strong>${String(nft)}</strong></div>` : ''}
    `;
  }

  function refreshEnabled() {
    btn.disabled = (status === 'paid') || !acceptedServer;
    if (acceptStatus) {
      acceptStatus.textContent = acceptedServer ? 'Terms accepted and stored in ledger.' : 'Terms not yet accepted.';
    }
  }
  refreshEnabled();

  // Signature pad helpers
  let drawing = false;
  let hasInk = false;
  let lastX = 0, lastY = 0;
  function canvasPos(ev) {
    const rect = sigCanvas.getBoundingClientRect();
    const t = ev.touches && ev.touches[0] ? ev.touches[0] : null;
    const cx = (t ? t.clientX : ev.clientX) - rect.left;
    const cy = (t ? t.clientY : ev.clientY) - rect.top;
    return { x: cx * (sigCanvas.width / rect.width), y: cy * (sigCanvas.height / rect.height) };
  }
  function drawLine(x1,y1,x2,y2) {
    const ctx = sigCanvas.getContext('2d');
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = '#111';
    ctx.lineWidth = 2.2;
    ctx.beginPath();
    ctx.moveTo(x1,y1);
    ctx.lineTo(x2,y2);
    ctx.stroke();
  }
  function start(ev) {
    drawing = true;
    const p = canvasPos(ev);
    lastX = p.x; lastY = p.y;
    ev.preventDefault?.();
  }
  function move(ev) {
    if (!drawing) return;
    const p = canvasPos(ev);
    drawLine(lastX,lastY,p.x,p.y);
    lastX = p.x; lastY = p.y;
    hasInk = true;
    ev.preventDefault?.();
  }
  function end() { drawing = false; }

  function openModal() {
    if (!signModal) return;
    signModal.style.display = 'block';
    if (sigMsg) sigMsg.textContent = '';
  }
  function closeModal() {
    if (!signModal) return;
    signModal.style.display = 'none';
  }

  if (openSign) openSign.addEventListener('click', openModal);
  if (closeSign) closeSign.addEventListener('click', closeModal);

  if (sigCanvas) {
    sigCanvas.addEventListener('mousedown', start);
    sigCanvas.addEventListener('mousemove', move);
    window.addEventListener('mouseup', end);
    sigCanvas.addEventListener('touchstart', start, { passive: false });
    sigCanvas.addEventListener('touchmove', move, { passive: false });
    sigCanvas.addEventListener('touchend', end);
  }
  if (sigClear) sigClear.addEventListener('click', () => {
    const ctx = sigCanvas.getContext('2d');
    ctx.clearRect(0, 0, sigCanvas.width, sigCanvas.height);
    hasInk = false;
    if (sigMsg) sigMsg.textContent = '';
  });

  if (sigSubmit) sigSubmit.addEventListener('click', async () => {
    const name = String(sigName?.value || '').trim();
    if (!name) { if (sigMsg) sigMsg.textContent = 'Full name is required.'; return; }
    if (!hasInk) { if (sigMsg) sigMsg.textContent = 'Please draw your signature.'; return; }
    if (sigMsg) sigMsg.textContent = 'Storing acceptance…';
    sigSubmit.disabled = true;
    try {
      const dataUrl = sigCanvas.toDataURL('image/png');
      const res = await acceptTerms(token, name, dataUrl);
      if (!res.ok) throw new Error(res.error);
      acceptedServer = true;
      refreshEnabled();
      if (sigMsg) sigMsg.textContent = 'Accepted and stored.';
      setTimeout(() => { closeModal(); }, 400);
    } catch (e) {
      if (sigMsg) sigMsg.textContent = String(e && e.message ? e.message : 'Acceptance failed');
    } finally {
      sigSubmit.disabled = false;
    }
  });

  // If not yet accepted, prompt immediately
  if (!acceptedServer) {
    setTimeout(() => { try { openModal(); } catch (_) {} }, 250);
  }

  btn.addEventListener('click', async () => {
    btn.disabled = true;
    msg.textContent = 'Processing payment…';
    const res = await pay(token);
    if (!res.ok) {
      msg.textContent = res.error;
      refreshEnabled();
      return;
    }
    msg.textContent = 'Payment completed. Thank you!';
  });
});

