/* Books-tied daily certificate badge on /cashflow-integrity.html (U6).
 * Reads GET /api/admin/cashflow/books-tied. Issue is POST on the same path.
 * Evidence only — never rewrites the money books. */
(function () {
  var root = document.getElementById('books-tied');
  if (!root) return;

  var token = localStorage.getItem('phins_token') || '';
  var headers = token
    ? { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' }
    : { 'Content-Type': 'application/json' };

  var verdictEl = document.getElementById('books-tied-verdict');
  var bodyEl = document.getElementById('books-tied-body');
  var stampEl = document.getElementById('books-tied-stamp');
  var issueBtn = document.getElementById('books-tied-issue');
  var refreshBtn = document.getElementById('books-tied-refresh');

  function esc(value) {
    return String(value || '').replace(/[&<>"']/g, function (ch) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch];
    });
  }

  function paint(status) {
    if (!status) {
      if (verdictEl) verdictEl.textContent = '';
      if (bodyEl) bodyEl.textContent = 'Certificate status unavailable.';
      return;
    }
    var fresh = !!status.fresh;
    var intact = !!status.intact;
    var label = fresh ? 'fresh' : intact ? 'stale' : status.present ? 'tampered' : 'missing';
    var tone = fresh ? 'clear' : intact ? 'watch' : 'attention';
    if (verdictEl) {
      verdictEl.innerHTML = '<span class="tag ' + tone + '">' + esc(label) + '</span>';
    }
    var lines = [];
    lines.push('UTC day ' + esc(status.utc_day || '—'));
    if (status.evaluated_at) {
      lines.push('Evaluated ' + esc(status.evaluated_at));
    }
    if (status.age_hours != null) {
      lines.push(
        'Age ' + Number(status.age_hours).toFixed(1) + ' h (max ' +
        Number(status.max_age_hours || 36).toFixed(0) + ' h)'
      );
    }
    if (status.digest) {
      lines.push('Digest ' + esc(String(status.digest).slice(0, 16)) + '…');
    }
    if (status.entry_id) {
      lines.push('Entry ' + esc(status.entry_id));
    }
    if (status.reason) {
      lines.push('Reason ' + esc(status.reason));
    }
    if (status.required === false) {
      lines.push('Freshness gate off for this process (PHINS_BOOKS_TIED_REQUIRE).');
    }
    if (bodyEl) bodyEl.textContent = lines.join(' · ');
    if (stampEl) {
      stampEl.textContent = status.event_type
        ? 'Ledger event ' + status.event_type
        : '';
    }
    if (issueBtn) {
      issueBtn.disabled = !!fresh;
    }
  }

  function load() {
    if (bodyEl) bodyEl.textContent = 'Reading today’s books-tied certificate…';
    return fetch('/api/admin/cashflow/books-tied', { headers: headers })
      .then(function (res) {
        return res.json().then(function (body) {
          return { ok: res.ok, body: body };
        });
      })
      .then(function (pack) {
        if (!pack.ok || !pack.body || !pack.body.books_tied) {
          paint(null);
          if (bodyEl) {
            bodyEl.textContent =
              (pack.body && pack.body.error) || 'Could not read books-tied status.';
          }
          return;
        }
        paint(pack.body.books_tied);
      })
      .catch(function () {
        paint(null);
        if (bodyEl) bodyEl.textContent = 'Could not reach books-tied status.';
      });
  }

  function issue() {
    if (!issueBtn) return;
    issueBtn.disabled = true;
    issueBtn.classList.add('is-busy');
    fetch('/api/admin/cashflow/books-tied', {
      method: 'POST',
      headers: headers,
      body: JSON.stringify({}),
    })
      .then(function (res) {
        return res.json().then(function (body) {
          return { ok: res.ok, status: res.status, body: body };
        });
      })
      .then(function (pack) {
        issueBtn.classList.remove('is-busy');
        if (pack.body && pack.body.books_tied) {
          paint(pack.body.books_tied);
        } else {
          load();
        }
        if (stampEl) {
          var cert = pack.body && pack.body.certificate;
          if (cert && cert.reason) {
            stampEl.textContent = 'Issue: ' + cert.reason;
          } else if (!pack.ok) {
            stampEl.textContent =
              (pack.body && pack.body.error) || ('HTTP ' + pack.status);
          }
        }
      })
      .catch(function () {
        issueBtn.classList.remove('is-busy');
        issueBtn.disabled = false;
        if (stampEl) stampEl.textContent = 'Issue request failed.';
      });
  }

  if (refreshBtn) refreshBtn.addEventListener('click', load);
  if (issueBtn) issueBtn.addEventListener('click', issue);
  load();
})();
