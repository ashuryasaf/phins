/**
 * Reads GET /api/admin/cashflow/period-close. Soft/hard close is POST.
 */
(function () {
  var root = document.getElementById('period-close');
  if (!root) return;

  function token() {
    try {
      return localStorage.getItem('phins_token') || sessionStorage.getItem('phins_token') || '';
    } catch (e) {
      return '';
    }
  }

  var verdictEl = document.getElementById('period-close-verdict');
  var bodyEl = document.getElementById('period-close-body');
  var stampEl = document.getElementById('period-close-stamp');
  var softBtn = document.getElementById('period-close-soft');
  var hardBtn = document.getElementById('period-close-hard');
  var refreshBtn = document.getElementById('period-close-refresh');

  function headers() {
    var h = { Accept: 'application/json' };
    var t = token();
    if (t) h.Authorization = 'Bearer ' + t;
    return h;
  }

  function paint(status) {
    if (!status) return;
    var current = status.current_period || {};
    var st = String(current.status || 'open');
    if (verdictEl) {
      verdictEl.textContent = st;
      verdictEl.className = st === 'hard' ? 'bad' : (st === 'soft' ? 'warn' : 'ok');
    }
    var lines = (status.trial_balance && status.trial_balance.lines) || [];
    var tbBits = lines.map(function (l) {
      return l.fund + ' net ' + (l.net != null ? l.net : '—');
    }).join(' · ');
    if (bodyEl) {
      bodyEl.textContent =
        'Period ' + (current.id || '—') +
        ' is ' + st +
        '. CoA fingerprint ' + ((status.coa && status.coa.chart_fingerprint) || '').slice(0, 12) +
        '… Soft close seals the TB; hard close refuses further posts in this month.' +
        (tbBits ? ' TB: ' + tbBits + '.' : '');
    }
    if (stampEl) {
      stampEl.textContent = current.updated_at
        ? ('Updated ' + current.updated_at)
        : '';
    }
    if (softBtn) softBtn.disabled = st === 'hard';
    if (hardBtn) hardBtn.disabled = st === 'hard';
  }

  function refresh() {
    if (bodyEl) bodyEl.textContent = 'Reading fiscal period status…';
    return fetch('/api/admin/cashflow/period-close', { headers: headers() })
      .then(function (r) {
        return r.json().then(function (body) {
          return { ok: r.ok, status: r.status, body: body };
        });
      })
      .then(function (pack) {
        if (!pack.ok) {
          if (bodyEl) {
            bodyEl.textContent =
              (pack.body && pack.body.error) || 'Could not read period-close status.';
          }
          return;
        }
        paint(pack.body && pack.body.period_close);
      })
      .catch(function () {
        if (bodyEl) bodyEl.textContent = 'Could not reach period-close status.';
      });
  }

  function postAction(action) {
    fetch('/api/admin/cashflow/period-close', {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, headers()),
      body: JSON.stringify({ action: action }),
    })
      .then(function (r) {
        return r.json().then(function (body) {
          return { ok: r.ok, body: body };
        });
      })
      .then(function (pack) {
        if (pack.ok && pack.body && pack.body.period_close) {
          paint(pack.body.period_close);
          return;
        }
        if (bodyEl) {
          bodyEl.textContent =
            (pack.body && (pack.body.error || pack.body.reason)) ||
            'Period-close action refused.';
        }
      })
      .catch(function () {
        if (bodyEl) bodyEl.textContent = 'Period-close action failed.';
      });
  }

  if (softBtn) softBtn.addEventListener('click', function () { postAction('soft'); });
  if (hardBtn) hardBtn.addEventListener('click', function () { postAction('hard'); });
  if (refreshBtn) refreshBtn.addEventListener('click', refresh);
  refresh();
})();
