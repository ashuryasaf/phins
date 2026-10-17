/*
 * PHINS Unified Business Plan — access layer for /business-plan.html.
 *
 * Asks GET /api/business-plan/access what this caller may do and then:
 *   - applies the admin-saved factor set as the page baseline (every viewer);
 *   - staff (admin): renders the admin tools inside the factor panel — save /
 *     clear the default factor set, choose which factors an open-link viewer
 *     may adjust, and set the founder portrait from an upload or the media
 *     library;
 *   - open-link viewer (signed NDA): the protected view — download, print,
 *     copy, drag, context menu and the common capture shortcuts are blocked,
 *     a watermark names the signer, the view blurs when it loses focus, only
 *     whitelisted factors stay editable, and access ends with the window or
 *     after the idle timeout (server-enforced; the page mirrors it).
 *
 * The browser cannot make a screenshot physically impossible; the server does
 * refuse every download for an open link and every opening is attributed to
 * the person who signed, which is what the undertaking relies on.
 */
(function () {
  'use strict';

  var BP = null;
  var UI = {};
  var LANG = (document.documentElement.getAttribute('lang') || 'en').toLowerCase();
  var ACCESS_URL = '/api/business-plan/access';
  var FACTORS_URL = '/api/business-plan/factors';
  var PORTRAIT_URL = '/api/business-plan/founder-portrait';

  function t(key, vars) {
    var s = UI[key] || key;
    Object.keys(vars || {}).forEach(function (k) { s = s.split('{' + k + '}').join(String(vars[k])); });
    return s;
  }
  function token() { try { return localStorage.getItem('phins_auth_token') || ''; } catch (e) { return ''; } }
  function authHeaders(json) {
    var h = {};
    var tk = token();
    if (tk) h['Authorization'] = 'Bearer ' + tk;
    if (json) h['Content-Type'] = 'application/json';
    return h;
  }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }
  function fmtWhen(iso) {
    if (!iso) return '';
    try { return new Date(iso).toLocaleString(LANG === 'he' ? 'he-IL' : 'en-GB', { hour12: false }); } catch (e) { return String(iso); }
  }
  function fmtLeft(ms) {
    if (ms < 0) ms = 0;
    var m = Math.floor(ms / 60000), h = Math.floor(m / 60); m = m % 60;
    return (h ? h + 'h ' : '') + m + 'm';
  }

  /* ------------------------------------------------------------------ */
  /* Protected view                                                      */
  /* ------------------------------------------------------------------ */
  function showOverlay(message, sticky) {
    var ov = document.getElementById('bp-protect-overlay');
    var msg = document.getElementById('bp-protect-message');
    if (!ov) return;
    if (msg) msg.textContent = message || '';
    ov.classList.add('on');
    ov.setAttribute('data-sticky', sticky ? '1' : '0');
  }
  function hideOverlay(force) {
    var ov = document.getElementById('bp-protect-overlay');
    if (!ov) return;
    if (!force && ov.getAttribute('data-sticky') === '1') return;
    ov.classList.remove('on');
  }

  function protect(access) {
    var viewer = access.viewer || {};
    var body = document.body;
    body.classList.add('bp-protected');

    // Hide every download / print affordance and neutralise the print button.
    var hide = document.querySelectorAll('[data-protected-hide]');
    for (var i = 0; i < hide.length; i++) { hide[i].setAttribute('hidden', ''); hide[i].style.display = 'none'; }
    try { window.print = function () { showOverlay(t('print_blocked'), false); setTimeout(function () { hideOverlay(false); }, 2500); }; } catch (e) {}

    // Watermark tiles name the signer on every screen (and in any capture).
    var wm = document.getElementById('bp-watermark');
    if (wm) {
      wm.innerHTML = '';
      var stamp = [viewer.signer_name, viewer.label, fmtWhen(viewer.opened_at)].filter(Boolean).join(' · ') || t('protected_view');
      var cols = 4, rows = 12;
      for (var r = 0; r < rows; r++) {
        for (var c = 0; c < cols; c++) {
          var tile = el('span', '', stamp);
          tile.style.left = ((c + (r % 2 ? 0.5 : 0)) * (100 / cols)) + '%';
          tile.style.top = (r * (100 / rows)) + '%';
          wm.appendChild(tile);
        }
      }
    }

    // Viewer note + countdown.
    var note = document.getElementById('bp-viewer-note');
    function renderNote() {
      if (!note) return;
      var until = viewer.access_until ? new Date(viewer.access_until).getTime() : 0;
      var left = until ? until - Date.now() : 0;
      var parts = [t('viewer_note', {
        label: viewer.label || '—',
        signer: viewer.signer_name || '—',
        when: fmtWhen(viewer.access_until),
        idle: Math.round((viewer.idle_timeout_seconds || 0) / 60)
      })];
      if (until) parts.push(t('expires_in', { time: fmtLeft(left) }));
      if (Array.isArray(access.adjustable)) parts.push(t('only_adjustable'));
      // Platform NDA receipt: registry instance + ledger sequence (language-neutral identifiers).
      if (viewer.nda_ledger && viewer.nda_ledger.entry_id) {
        parts.push('NDA ' + (viewer.nda_doc_instance_id || '') + ' · ledger #' + (viewer.nda_ledger.sequence_no || '') +
          ' · ' + String(viewer.nda_ledger.entry_hash || '').slice(0, 12) + '…');
      }
      note.textContent = parts.join(' ');
      note.classList.add('on');
      if (until && left <= 0) expire();
    }
    var expired = false;
    function expire() {
      if (expired) return;
      expired = true;
      body.classList.add('bp-expired');
      showOverlay(t('expired'), true);
    }
    renderNote();
    setInterval(renderNote, 30000);

    // Only the whitelisted factors stay editable.
    if (BP && Array.isArray(access.adjustable)) BP.setAdjustable(access.adjustable);

    // Block copy / context menu / drag / selection and the capture shortcuts.
    function swallow(ev) { ev.preventDefault(); ev.stopPropagation(); return false; }
    ['contextmenu', 'copy', 'cut', 'dragstart', 'selectstart'].forEach(function (name) {
      document.addEventListener(name, function (ev) {
        var tgt = ev.target;
        if (tgt && (tgt.tagName === 'INPUT' || tgt.tagName === 'TEXTAREA') && name === 'selectstart') return true;
        return swallow(ev);
      }, true);
    });
    document.addEventListener('keydown', function (ev) {
      var key = (ev.key || '').toLowerCase();
      var mod = ev.ctrlKey || ev.metaKey;
      if (key === 'printscreen') { swallow(ev); try { navigator.clipboard && navigator.clipboard.writeText(''); } catch (e) {} showOverlay(t('print_blocked'), false); setTimeout(function () { hideOverlay(false); }, 2000); return; }
      if (mod && ['p', 's', 'u', 'c', 'x', 'a'].indexOf(key) >= 0) { swallow(ev); if (key === 'p') showOverlay(t('print_blocked'), false), setTimeout(function () { hideOverlay(false); }, 2000); return; }
      if (mod && ev.shiftKey && ['i', 'j', 'c', 's', '3', '4', '5'].indexOf(key) >= 0) { swallow(ev); return; }
      if (key === 'f12') { swallow(ev); return; }
    }, true);
    document.addEventListener('keyup', function (ev) {
      if ((ev.key || '').toLowerCase() === 'printscreen') { try { navigator.clipboard && navigator.clipboard.writeText(''); } catch (e) {} }
    }, true);
    window.addEventListener('beforeprint', function () { body.classList.add('bp-print-blocked'); });
    window.addEventListener('afterprint', function () { body.classList.remove('bp-print-blocked'); });

    // Blur the view whenever it is not the focused, visible window.
    var paused = false;
    function pause() { if (expired) return; paused = true; body.classList.add('bp-blurred'); showOverlay(t('blurred'), false); }
    function resume() { if (expired) return; paused = false; body.classList.remove('bp-blurred'); hideOverlay(false); ping(); }
    window.addEventListener('blur', pause);
    window.addEventListener('focus', resume);
    document.addEventListener('visibilitychange', function () { if (document.hidden) pause(); else resume(); });
    var ov = document.getElementById('bp-protect-overlay');
    if (ov) ov.addEventListener('click', function () { if (!expired) { window.focus(); resume(); } });

    // Mirror the server: keep the session alive while the tab is in use and
    // close the view the moment the server says the opening has ended. A
    // paused (blurred) view is not in use, so it must not refresh the
    // server-side activity stamp — otherwise the idle timeout never fires.
    // Returning to the view asks again at once, so an opening the server has
    // already closed does not stay readable until the next tick.
    function ping() {
      if (expired || paused || document.hidden) return;
      fetch(ACCESS_URL, { credentials: 'same-origin', cache: 'no-store' }).then(function (r) {
        if (r.status === 401 || r.status === 403) { expire(); return null; }
        return r.ok ? r.json() : null;
      }).then(function (data) {
        if (data && data.mode === 'share' && data.viewer) { viewer = data.viewer; renderNote(); }
        else if (data && data.mode !== 'share' && data.mode !== 'staff' && data.mode !== 'public') expire();
      }).catch(function () {});
    }
    setInterval(ping, 60000);
  }

  /* ------------------------------------------------------------------ */
  /* Admin tools                                                         */
  /* ------------------------------------------------------------------ */
  function adminTools(access) {
    var host = document.getElementById('bp-admin-tools');
    if (!host || !BP) return;
    host.innerHTML = '';
    host.removeAttribute('hidden');
    host.appendChild(el('h4', '', t('admin_tools')));

    // -- Saved default factor set -------------------------------------
    var row = el('div', 'bp-admin-row');
    var saveBtn = el('button', 'bp-btn gold', t('save_default')); saveBtn.type = 'button';
    var clearBtn = el('button', 'bp-btn', t('clear_default')); clearBtn.type = 'button';
    var status = el('span', 'bp-status', '');
    row.appendChild(saveBtn); row.appendChild(clearBtn); row.appendChild(status);
    host.appendChild(row);

    host.appendChild(el('h4', '', t('viewer_adjustable')));
    var grid = el('div', 'bp-adjustable-grid');
    var whitelist = access.viewer_adjustable;
    var allAllowed = whitelist === 'all' || whitelist === null || whitelist === undefined;
    var boxes = {};
    BP.factors.forEach(function (f) {
      var label = el('label', '');
      var cb = document.createElement('input'); cb.type = 'checkbox'; cb.value = f.id;
      cb.checked = allAllowed || (Array.isArray(whitelist) && whitelist.indexOf(f.id) >= 0);
      boxes[f.id] = cb;
      label.appendChild(cb); label.appendChild(document.createTextNode(' ' + f.label));
      grid.appendChild(label);
    });
    host.appendChild(grid);

    function selectedWhitelist() {
      var ids = BP.factors.filter(function (f) { return boxes[f.id].checked; }).map(function (f) { return f.id; });
      return ids.length === BP.factors.length ? 'all' : ids;
    }
    function postFactors(body) {
      status.textContent = '…';
      return fetch(FACTORS_URL, { method: 'POST', headers: authHeaders(true), credentials: 'same-origin', body: JSON.stringify(body) })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d || {} }; }); });
    }
    saveBtn.addEventListener('click', function () {
      var factors = {};
      BP.factors.forEach(function (f) { if (BP.state[f.id] !== f.default) factors[f.id] = BP.state[f.id]; });
      postFactors({ factors: factors, viewer_adjustable: selectedWhitelist() }).then(function (res) {
        if (!res.ok) { status.textContent = t('save_failed', { error: res.data.error || res.status }); return; }
        status.textContent = t('saved_ok');
        BP.setBaseline((res.data.settings || {}).saved_factors || {});
      }).catch(function (e) { status.textContent = t('save_failed', { error: e }); });
    });
    clearBtn.addEventListener('click', function () {
      postFactors({ clear: true }).then(function (res) {
        if (!res.ok) { status.textContent = t('save_failed', { error: res.data.error || res.status }); return; }
        status.textContent = t('cleared_ok');
        BP.setBaseline({});
        BP.factors.forEach(function (f) { boxes[f.id].checked = true; });
      }).catch(function (e) { status.textContent = t('save_failed', { error: e }); });
    });

    // -- Founder portrait ---------------------------------------------
    if (access.can_manage_portrait) {
      host.appendChild(el('h4', '', t('founder_portrait')));
      var prow = el('div', 'bp-admin-row');
      var preview = document.createElement('img'); preview.className = 'bp-portrait-preview'; preview.alt = t('founder_portrait');
      preview.src = PORTRAIT_URL + '?v=' + Date.now();
      preview.addEventListener('error', function () { preview.classList.add('missing'); preview.alt = t('no_portrait'); });
      prow.appendChild(preview);

      var controls = el('div', 'bp-admin-col');
      var fileLabel = el('label', 'bp-btn', t('upload_photo'));
      var file = document.createElement('input'); file.type = 'file'; file.accept = 'image/*'; file.hidden = true;
      fileLabel.appendChild(file);
      controls.appendChild(fileLabel);

      var pickRow = el('div', 'bp-admin-row');
      var select = document.createElement('select');
      var placeholder = document.createElement('option'); placeholder.value = ''; placeholder.textContent = t('select_image');
      select.appendChild(placeholder);
      var applyBtn = el('button', 'bp-btn', t('apply')); applyBtn.type = 'button';
      pickRow.appendChild(el('span', 'bp-status', t('pick_media')));
      pickRow.appendChild(select); pickRow.appendChild(applyBtn);
      controls.appendChild(pickRow);
      var pstatus = el('span', 'bp-status', '');
      controls.appendChild(pstatus);
      prow.appendChild(controls);
      host.appendChild(prow);

      function refreshPortrait() {
        var bust = '?v=' + Date.now();
        preview.classList.remove('missing');
        preview.src = PORTRAIT_URL + bust;
        var photos = document.querySelectorAll('.bp-founder-photo img');
        for (var i = 0; i < photos.length; i++) { photos[i].parentNode.classList.remove('fallback'); photos[i].src = PORTRAIT_URL + bust; }
      }
      function assign(assetId) {
        pstatus.textContent = '…';
        return fetch('/api/design/settings', { method: 'POST', headers: authHeaders(true), credentials: 'same-origin', body: JSON.stringify({ founder_portrait_id: assetId }) })
          .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d || {} }; }); })
          .then(function (res) {
            if (!res.ok) { pstatus.textContent = t('portrait_failed', { error: res.data.error || res.status }); return false; }
            pstatus.textContent = t('portrait_updated');
            refreshPortrait();
            return true;
          });
      }
      function loadLibrary() {
        if (!token()) return;
        fetch('/api/media', { headers: authHeaders(false), credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : null; }).then(function (data) {
          if (!data || !Array.isArray(data.assets)) return;
          data.assets.filter(function (a) { return a.type === 'image'; }).forEach(function (a) {
            var opt = document.createElement('option'); opt.value = a.id; opt.textContent = a.name || a.id; select.appendChild(opt);
          });
        }).catch(function () {});
      }
      file.addEventListener('change', function () {
        var f = file.files && file.files[0];
        if (!f) return;
        if (!token()) { pstatus.textContent = t('portrait_failed', { error: 'sign in' }); return; }
        var reader = new FileReader();
        reader.onload = function () {
          pstatus.textContent = '…';
          fetch('/api/media', { method: 'POST', headers: authHeaders(true), credentials: 'same-origin', body: JSON.stringify({ name: f.name || 'founder-portrait', type: 'image', format: f.type || 'image/jpeg', size: f.size, data: reader.result, source: 'business-plan' }) })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d || {} }; }); })
            .then(function (res) {
              if (!res.ok || !res.data.asset) { pstatus.textContent = t('portrait_failed', { error: res.data.error || res.status }); return; }
              var opt = document.createElement('option'); opt.value = res.data.asset.id; opt.textContent = res.data.asset.name || res.data.asset.id; select.appendChild(opt); select.value = opt.value;
              assign(res.data.asset.id);
            }).catch(function (e) { pstatus.textContent = t('portrait_failed', { error: e }); });
        };
        reader.readAsDataURL(f);
      });
      applyBtn.addEventListener('click', function () { if (select.value) assign(select.value); });
      loadLibrary();
    }
  }

  /* ------------------------------------------------------------------ */
  function boot() {
    BP = window.PhinsBusinessPlan || null;
    UI = (BP && BP.ui) || {};
    fetch(ACCESS_URL, { credentials: 'same-origin', cache: 'no-store' }).then(function (r) {
      if (!r.ok) return null;
      return r.json();
    }).then(function (access) {
      if (!access) return;
      window.PhinsBusinessPlanAccess = access;
      if (BP && access.saved_factors && Object.keys(access.saved_factors).length) BP.setBaseline(access.saved_factors);
      if (access.mode === 'share') protect(access);
      else if (access.mode === 'staff' && access.can_save_factors) adminTools(access);
      try { window.dispatchEvent(new CustomEvent('phins:business-plan-access', { detail: access })); } catch (e) {}
    }).catch(function () {});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
