/**
 * Trust + cession badge on /cashflow-integrity.html (U10).
 * Reads GET /api/admin/cashflow/trust. Findings only — never invents cash.
 */
(function () {
  var root = document.getElementById('trust-recon');
  if (!root) return;

  function token() {
    try {
      return localStorage.getItem('phins_token') || sessionStorage.getItem('phins_token') || '';
    } catch (e) {
      return '';
    }
  }

  var verdictEl = document.getElementById('trust-verdict');
  var bodyEl = document.getElementById('trust-body');
  var stampEl = document.getElementById('trust-stamp');
  var refreshBtn = document.getElementById('trust-refresh');

  function headers() {
    var h = { Accept: 'application/json' };
    var t = token();
    if (t) h.Authorization = 'Bearer ' + t;
    return h;
  }

  function paint(status) {
    if (!status) return;
    var ok = !!status.ok;
    var findings = status.findings || [];
    var label = ok ? 'tied' : (findings.some(function (f) {
      return f.code === 'trust_deficit';
    }) ? 'deficit' : 'review');
    if (verdictEl) {
      verdictEl.textContent = label;
      verdictEl.className = ok ? 'ok' : 'bad';
    }
    var trust = status.trust || {};
    var cession = status.cession || {};
    var bits = [
      'trust balance $' + Number(trust.balance || 0).toFixed(2),
      'held $' + Number(trust.premium_held || 0).toFixed(2),
      'released $' + Number(trust.remittance_released || 0).toFixed(2),
      'ceded premium $' + Number(cession.ceded_premium || 0).toFixed(2),
    ];
    if (findings.length) {
      bits.push(findings.map(function (f) { return f.code; }).join(', '));
    }
    if (bodyEl) {
      bodyEl.textContent =
        'Binder ' + (status.binder_id || 'PHINS-DEFAULT') + '. ' +
        bits.join(' · ') +
        '. Auto-fill forbidden.';
    }
    if (stampEl) {
      stampEl.textContent = status.reconciled_at ? ('Updated ' + status.reconciled_at) : '';
    }
  }

  function refresh() {
    if (bodyEl) bodyEl.textContent = 'Reading trust status…';
    return fetch('/api/admin/cashflow/trust', { headers: headers() })
      .then(function (r) {
        return r.json().then(function (body) {
          return { ok: r.ok, body: body };
        });
      })
      .then(function (pack) {
        if (!pack.ok) {
          if (bodyEl) {
            bodyEl.textContent =
              (pack.body && pack.body.error) || 'Could not read trust status.';
          }
          return;
        }
        paint(pack.body && pack.body.trust);
      })
      .catch(function () {
        if (bodyEl) bodyEl.textContent = 'Could not reach trust status.';
      });
  }

  if (refreshBtn) refreshBtn.addEventListener('click', refresh);
  refresh();
})();
