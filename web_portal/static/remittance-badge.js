/**
 * Remittance + bordereaux badge on /cashflow-integrity.html (U9 / AE5).
 * Reads GET /api/admin/cashflow/remittance?period_id=YYYY-MM. Build/settle is POST.
 */
(function () {
  var root = document.getElementById('remittance');
  if (!root) return;

  function token() {
    try {
      return localStorage.getItem('phins_token') || sessionStorage.getItem('phins_token') || '';
    } catch (e) {
      return '';
    }
  }

  var verdictEl = document.getElementById('remittance-verdict');
  var bodyEl = document.getElementById('remittance-body');
  var stampEl = document.getElementById('remittance-stamp');
  var buildBtn = document.getElementById('remittance-build');
  var settleBtn = document.getElementById('remittance-settle');
  var refreshBtn = document.getElementById('remittance-refresh');
  var lastPayableId = '';
  var lastPeriodId = '';

  function currentPeriodId() {
    var d = new Date();
    var m = d.getUTCMonth() + 1;
    return d.getUTCFullYear() + '-' + (m < 10 ? '0' + m : String(m));
  }

  function headers() {
    var h = { Accept: 'application/json' };
    var t = token();
    if (t) h.Authorization = 'Bearer ' + t;
    return h;
  }

  function paint(status) {
    if (!status) return;
    lastPeriodId = String(status.period_id || currentPeriodId());
    var runs = status.runs || [];
    var boards = status.bordereaux || [];
    // Scoped to one period — prefer the settled run's remitted cash over a
    // later rebuild board so post-settle premium never looks already paid.
    var payable = runs.filter(function (r) { return r.status === 'payable'; });
    var settled = runs.filter(function (r) { return r.status === 'settled'; });
    var settledRun = settled.length ? settled[settled.length - 1] : null;
    var board = boards.length ? boards[boards.length - 1] : {};
    if (settledRun) {
      board = {
        premium_cash: settledRun.premium_cash,
        carrier_payable: settledRun.amount,
        bordereau_sha256: settledRun.bordereau_sha256,
        ae5_ok: true,
        built_at: settledRun.settled_at,
      };
    }
    lastPayableId = payable.length ? String(payable[payable.length - 1].id || '') : '';
    var label = settledRun && !payable.length
      ? 'settled'
      : (payable.length ? 'payable' : (boards.length ? 'sealed' : 'idle'));
    if (verdictEl) {
      verdictEl.textContent = label;
      verdictEl.className = label === 'settled' ? 'ok' : (label === 'payable' ? 'warn' : 'ok');
    }
    var bits = [];
    if (board.premium_cash != null) bits.push('premium $' + Number(board.premium_cash).toFixed(2));
    if (board.carrier_payable != null) {
      bits.push(
        (settledRun ? 'remitted $' : 'carrier payable $') +
        Number(board.carrier_payable).toFixed(2)
      );
    }
    if (board.ae5_ok === false) bits.push('AE5 seal failed');
    else if (board.bordereau_sha256) bits.push('AE5 seal ' + String(board.bordereau_sha256).slice(0, 12) + '…');
    bits.push(payable.length + ' payable · ' + settled.length + ' settled');
    if (bodyEl) {
      bodyEl.textContent =
        'Binder ' + (status.binder_id || status.default_binder_id || 'PHINS-DEFAULT') +
        ' · period ' + lastPeriodId +
        '. ' + bits.join(' · ') +
        '. Settle authorizes through Money Gate remittance.settle.';
    }
    if (stampEl) {
      var stamp = (payable[0] && payable[0].created_at) || (settled[0] && settled[0].settled_at) || (board.built_at) || '';
      stampEl.textContent = stamp ? ('Updated ' + stamp) : '';
    }
    if (settleBtn) settleBtn.disabled = !lastPayableId;
  }

  function refresh() {
    if (bodyEl) bodyEl.textContent = 'Reading remittance status…';
    var period = lastPeriodId || currentPeriodId();
    return fetch('/api/admin/cashflow/remittance?period_id=' + encodeURIComponent(period), {
      headers: headers(),
    })
      .then(function (r) {
        return r.json().then(function (body) {
          return { ok: r.ok, body: body };
        });
      })
      .then(function (pack) {
        if (!pack.ok) {
          if (bodyEl) {
            bodyEl.textContent =
              (pack.body && pack.body.error) || 'Could not read remittance status.';
          }
          return;
        }
        paint(pack.body && pack.body.remittance);
      })
      .catch(function () {
        if (bodyEl) bodyEl.textContent = 'Could not reach remittance status.';
      });
  }

  function postAction(body) {
    var payload = Object.assign({ period_id: lastPeriodId || currentPeriodId() }, body || {});
    fetch('/api/admin/cashflow/remittance', {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, headers()),
      body: JSON.stringify(payload),
    })
      .then(function (r) {
        return r.json().then(function (resp) {
          return { ok: r.ok, body: resp };
        });
      })
      .then(function (pack) {
        if (pack.ok && pack.body && pack.body.remittance) {
          paint(pack.body.remittance);
          return;
        }
        if (bodyEl) {
          bodyEl.textContent =
            (pack.body && (pack.body.error || pack.body.reason)) ||
            'Remittance action refused.';
        }
      })
      .catch(function () {
        if (bodyEl) bodyEl.textContent = 'Remittance action failed.';
      });
  }

  if (buildBtn) {
    buildBtn.addEventListener('click', function () {
      postAction({ action: 'build' });
    });
  }
  if (settleBtn) {
    settleBtn.addEventListener('click', function () {
      if (!lastPayableId) return;
      postAction({ action: 'settle', run_id: lastPayableId });
    });
  }
  if (refreshBtn) refreshBtn.addEventListener('click', refresh);
  refresh();
})();
