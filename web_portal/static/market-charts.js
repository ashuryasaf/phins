function parseSymbols(str) {
  return String(str || '')
    .split(',')
    .map(s => s.trim().toUpperCase())
    .filter(Boolean)
    .slice(0, 12);
}

function drawSparkline(canvas, points, color) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  if (!points || points.length < 2) {
    ctx.fillStyle = 'rgba(0,0,0,0.25)';
    ctx.fillText('—', w / 2, h / 2);
    return;
  }
  const ys = points.map(p => Number(p.p));
  const min = Math.min(...ys);
  const max = Math.max(...ys);
  const span = max - min || 1;

  ctx.lineWidth = 2;
  ctx.strokeStyle = color;
  ctx.beginPath();
  points.forEach((p, i) => {
    const x = (i / (points.length - 1)) * (w - 4) + 2;
    const y = h - 2 - ((Number(p.p) - min) / span) * (h - 4);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

async function fetchQuotes(kind, symbols) {
  const qs = new URLSearchParams();
  qs.set('symbols', symbols.join(','));
  if (kind === 'crypto') qs.set('vs', 'USD');
  if (kind === 'index') qs.set('currency', 'USD');
  const resp = await fetch(`/api/market/${kind === 'index' ? 'indexes' : 'crypto'}?${qs.toString()}`);
  const data = await resp.json();
  return Array.isArray(data.items) ? data.items : [];
}

async function fetchSeries(kind, symbols, points) {
  const qs = new URLSearchParams();
  qs.set('kind', kind);
  qs.set('symbols', symbols.join(','));
  qs.set('points', String(points || 60));
  const resp = await fetch(`/api/market/series?${qs.toString()}`);
  const data = await resp.json();
  return Array.isArray(data.items) ? data.items : [];
}

function formatPrice(x) {
  const n = Number(x || 0);
  return n.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

async function renderMarketCharts(rootId, opts) {
  const root = document.getElementById(rootId);
  if (!root) return;

  const cryptoInput = root.querySelector('[data-kind="crypto"][data-role="symbols"]');
  const indexInput = root.querySelector('[data-kind="index"][data-role="symbols"]');
  const refreshBtn = root.querySelector('[data-role="refresh"]');
  const statusEl = root.querySelector('[data-role="status"]');

  const storeKeyCrypto = opts?.storeKeyCrypto || 'phins_market_crypto';
  const storeKeyIndex = opts?.storeKeyIndex || 'phins_market_index';

  if (cryptoInput && localStorage.getItem(storeKeyCrypto)) cryptoInput.value = localStorage.getItem(storeKeyCrypto);
  if (indexInput && localStorage.getItem(storeKeyIndex)) indexInput.value = localStorage.getItem(storeKeyIndex);

  async function refresh() {
    const cryptoSyms = parseSymbols(cryptoInput?.value || 'BTC,ETH');
    const indexSyms = parseSymbols(indexInput?.value || 'SPX,NASDAQ');
    if (cryptoInput) localStorage.setItem(storeKeyCrypto, cryptoSyms.join(','));
    if (indexInput) localStorage.setItem(storeKeyIndex, indexSyms.join(','));

    if (statusEl) statusEl.textContent = 'Updating…';

    // Trigger quote fetch (also feeds series server-side)
    const [cryptoQuotes, indexQuotes] = await Promise.all([
      fetchQuotes('crypto', cryptoSyms),
      fetchQuotes('index', indexSyms),
    ]);
    const [cryptoSeries, indexSeries] = await Promise.all([
      fetchSeries('crypto', cryptoSyms, 60),
      fetchSeries('index', indexSyms, 60),
    ]);

    function block(title, kind, quotes, series, color) {
      const m = new Map(quotes.map(q => [q.symbol, q]));
      const s = new Map(series.map(x => [x.symbol, x.points || []]));
      const rows = (kind === 'crypto' ? cryptoSyms : indexSyms).map(sym => {
        const q = m.get(sym) || {};
        const pts = s.get(sym) || [];
        const id = `${rootId}-${kind}-${sym}`;
        return `
          <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:10px 0; border-bottom:1px solid var(--border)">
            <div style="min-width:92px">
              <div style="font-weight:800">${sym}</div>
              <div style="color:var(--muted); font-size:12px">${q.source || 'fallback'}</div>
            </div>
            <canvas id="${id}" width="140" height="34" style="border-radius:8px; background:rgba(11,42,90,0.04)"></canvas>
            <div style="min-width:120px; text-align:right">
              <div style="font-weight:800">${formatPrice(q.price)}</div>
              <div style="color:var(--muted); font-size:12px">${q.updated_at ? new Date(q.updated_at).toLocaleTimeString() : ''}</div>
            </div>
          </div>
        `;
      }).join('');
      return `
        <div style="flex:1; min-width:280px">
          <div style="font-weight:900; margin-bottom:8px">${title}</div>
          <div class="card" style="padding:12px">${rows}</div>
        </div>
      `;
    }

    root.querySelector('[data-role="charts"]').innerHTML = `
      <div style="display:flex; gap:16px; flex-wrap:wrap">
        ${block('Crypto', 'crypto', cryptoQuotes, cryptoSeries, '#0b6cff')}
        ${block('Indexes', 'index', indexQuotes, indexSeries, '#f15bb5')}
      </div>
    `;

    // draw after DOM insert
    cryptoSeries.forEach(s => {
      const c = document.getElementById(`${rootId}-crypto-${s.symbol}`);
      if (c) drawSparkline(c, s.points || [], '#0b6cff');
    });
    indexSeries.forEach(s => {
      const c = document.getElementById(`${rootId}-index-${s.symbol}`);
      if (c) drawSparkline(c, s.points || [], '#f15bb5');
    });

    if (statusEl) statusEl.textContent = 'Live when available, fallback otherwise.';
  }

  if (refreshBtn) refreshBtn.addEventListener('click', refresh);
  await refresh();
  const interval = Number(opts?.intervalSeconds || 30);
  setInterval(refresh, Math.max(10, interval) * 1000);
}

