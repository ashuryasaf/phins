/* ============================================================================
 * PHINS — Adjustable Legal / Corporate / Funding Document Engine
 * ----------------------------------------------------------------------------
 * window.PhinsLegalDoc.init(config) powers every /legal/*.html document:
 *   • editable, context/audience-aware fields bound into the document body
 *   • role presets (e.g. per admin-dashboard position)
 *   • deterministic computed values + editable tables (cap table, model, etc.)
 *   • LIVE signature panels (draw-to-sign canvas OR typed) per relevant entity
 *   • SHA-256 content hashing (Web Crypto) + lock-after-sign + tamper detection
 *   • localStorage persistence so a filled, signed document survives reload
 *   • tamper-evident anchoring into the PHINS hash-chained platform event ledger
 *     via /api/legal-docs/sign + /verify + /registry (best-effort, offline-safe)
 *
 * Data-integrity contract: a signature locks its panel; the FIRST signature
 * freezes the document content hash (all signatories attest to the same hash);
 * editing locked content is blocked; "Unlock & void" never silently deletes —
 * it records a legal_document_voided event. Nothing is anchored without an
 * explicit human signature.
 * ==========================================================================*/
(function () {
  'use strict';

  var API = {
    sign: '/api/legal-docs/sign',
    verify: '/api/legal-docs/verify',
    registry: '/api/legal-docs/registry'
  };

  // ---------------------------------------------------------------- helpers
  function $(sel, root) { return (root || document).querySelector(sel); }
  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function rand(n) {
    var s = '', c = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
    for (var i = 0; i < (n || 6); i++) s += c[Math.floor(Math.random() * c.length)];
    return s;
  }
  function safeNum(v, d) { var n = parseFloat(v); return isFinite(n) ? n : (d || 0); }
  function cssEsc(s) { return (window.CSS && CSS.escape) ? CSS.escape(s) : String(s).replace(/[^\w-]/g, '\\$&'); }

  function fmt(value, type, currency) {
    if (value == null || value === '') return '';
    if (type === 'currency') {
      var n = safeNum(value, 0);
      var sym = currency || '$';
      return sym + n.toLocaleString(undefined, { maximumFractionDigits: 2 });
    }
    if (type === 'percent') return safeNum(value, 0).toLocaleString(undefined, { maximumFractionDigits: 2 }) + '%';
    if (type === 'number') return safeNum(value, 0).toLocaleString();
    if (type === 'date') {
      var d = new Date(value + 'T00:00:00');
      if (isNaN(d)) return value;
      return d.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
    }
    return String(value);
  }

  // stable stringify (sorted keys) for deterministic hashing
  function stableStringify(obj) {
    if (obj === null || typeof obj !== 'object') return JSON.stringify(obj);
    if (Array.isArray(obj)) return '[' + obj.map(stableStringify).join(',') + ']';
    var keys = Object.keys(obj).sort();
    return '{' + keys.map(function (k) {
      return JSON.stringify(k) + ':' + stableStringify(obj[k]);
    }).join(',') + '}';
  }

  function sha256Hex(str) {
    if (window.crypto && window.crypto.subtle) {
      var data = new TextEncoder().encode(str);
      return window.crypto.subtle.digest('SHA-256', data).then(function (buf) {
        var arr = Array.from(new Uint8Array(buf));
        return arr.map(function (b) { return b.toString(16).padStart(2, '0'); }).join('');
      });
    }
    // Deterministic non-crypto fallback (older/insecure contexts) — clearly 64 hex.
    return Promise.resolve(fallbackHash(str));
  }
  function fallbackHash(str) {
    var h1 = 0x811c9dc5, h2 = 0xc2b2ae35, out = '';
    for (var i = 0; i < str.length; i++) {
      var c = str.charCodeAt(i);
      h1 = (h1 ^ c) >>> 0; h1 = (h1 * 0x01000193) >>> 0;
      h2 = (h2 ^ ((c << 3) | (c >> 1))) >>> 0; h2 = (h2 * 0x85ebca6b) >>> 0;
    }
    for (var j = 0; j < 8; j++) {
      h1 = (h1 * 0x01000193 + j) >>> 0; h2 = (h2 * 0x85ebca6b + j) >>> 0;
      out += (h1 >>> 0).toString(16).padStart(8, '0');
    }
    return out.slice(0, 64);
  }

  function postJSON(url, body) {
    var headers = { 'Content-Type': 'application/json' };
    // Attach the PHINS session token when present so privileged actions (e.g.
    // voiding signatures) are authenticated. Anchoring a signature stays
    // session-optional server-side, so omitting the token for counterparties is
    // still fine; voiding requires an authenticated session.
    try {
      var token = localStorage.getItem('phins_token');
      if (token) headers['Authorization'] = 'Bearer ' + token;
    } catch (e) {}
    return fetch(url, {
      method: 'POST', headers: headers,
      body: JSON.stringify(body)
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, data: j }; }); });
  }

  // ----------------------------------------------------------------- engine
  function LegalDoc(cfg) {
    this.cfg = cfg;
    this.contexts = (cfg.contexts || []).map(function (c) {
      return typeof c === 'string' ? { id: c, label: c.charAt(0).toUpperCase() + c.slice(1) } : c;
    });
    this.context = cfg.defaultContext || (this.contexts[0] && this.contexts[0].id) || 'default';
    this.fields = cfg.fields || [];
    this.tables = cfg.tables || [];
    this.signatories = cfg.signatories || [];
    this.values = {};
    this.tableData = {};
    this.signatures = {};      // role -> {signerName, signerTitle, method, signatureData, signedAt, receipt}
    this.lockedHash = null;    // frozen content hash at first signature
    this.locking = false;      // synchronous lock engaged at sign click, before async hash resolves
    this.hydrating = false;    // registry fetch in flight for a shared ?doc= link, before signed state loads
    this.storageKey = null;
    this.bindEls = {};
  }

  LegalDoc.prototype.locked = function () { return !!this.lockedHash || this.locking || this.hydrating; };

  LegalDoc.prototype.boot = function () {
    var self = this;
    // default values
    this.fields.forEach(function (f) { self.values[f.key] = (f.default != null ? f.default : ''); });
    this.tables.forEach(function (t) {
      self.tableData[t.key] = (t.default || []).map(function (r) { return Object.assign({}, r); });
    });
    // Pre-fill the investor name from the shared Deal & Valuation Configurator
    // BEFORE restoring any saved/anchored instance, so saved values always win.
    this.applySharedInvestorDefaults();
    // instance id (restore if same doc opened before, else mint)
    this.loadOrMint();
    // A shared link must not be editable or signable until the registry fetch
    // resolves, otherwise edits/signatures made during the in-flight window
    // produce a hash that conflicts with the already-anchored content.
    this.hydrating = !!this._needsRegistryHydration;
    this.render();
    this.recompute();
    this.refreshIntegrity();
    if (this._needsRegistryHydration) this.loadFromRegistry();
  };

  // Reflect the investor named in the pitch-dashboard Deal & Valuation
  // Configurator (shared localStorage key) onto any investor document that has
  // an `investorName` field. Only fills the field while it is still at its empty
  // default, so a previously saved or ledger-anchored value is never overwritten.
  LegalDoc.prototype.applySharedInvestorDefaults = function () {
    try {
      if (!this.fields.some(function (f) { return f.key === 'investorName'; })) return;
      if ((('' + (this.values.investorName || '')).trim())) return;
      var raw = localStorage.getItem('phins.investor.cfg.v1');
      if (!raw) return;
      var shared = JSON.parse(raw);
      var name = shared && typeof shared === 'object' ? ('' + (shared.investorName || '')).trim() : '';
      if (name) this.values.investorName = name;
    } catch (e) {}
  };

  LegalDoc.prototype.loadOrMint = function () {
    var self = this;
    // pointer to the most recent instance of this docType in this browser
    var ptrKey = 'phins.legal.ptr.' + this.cfg.docType;
    var id = null;
    var fromQuery = false;
    try {
      var q = new URLSearchParams(location.search).get('doc');
      if (q) { id = q; fromQuery = true; }
      if (!id) id = localStorage.getItem(ptrKey);
    } catch (e) {}
    if (id) {
      try {
        var raw = localStorage.getItem('phins.legal.' + id);
        if (raw) {
          var st = JSON.parse(raw);
          this.docInstanceId = id;
          this.context = st.context || this.context;
          Object.assign(this.values, st.fieldValues || {});
          if (st.tableData) this.tableData = st.tableData;
          this.signatures = st.signatures || {};
          this.lockedHash = st.lockedHash || null;
        }
      } catch (e) {}
    }
    // Honor a known instance id — from an explicit ?doc= link OR this browser's
    // stored pointer — even without a local snapshot, so the document resolves to
    // the same ledger-anchored instance on any device.
    if (!this.docInstanceId && id) this.docInstanceId = id;
    // Any previously-known instance must reconcile against the ledger during
    // boot — whether opened via a shared ?doc= link or restored from the stored
    // pointer/local snapshot — because a co-signer's anchor, void, or re-sign in
    // another session would otherwise stay invisible, leaving cached
    // signed/locked state on screen. Only a freshly minted instance (no id yet)
    // skips hydration, since it has nothing anchored to reconcile with.
    this._needsRegistryHydration = !!id;
    if (!this.docInstanceId) {
      var stamp = new Date().toISOString().slice(0, 10).replace(/-/g, '');
      this.docInstanceId = 'LGL-' + this.cfg.docType.toUpperCase().replace(/[^A-Z0-9]+/g, '-') +
        '-' + stamp + '-' + rand(6);
    }
    this.storageKey = 'phins.legal.' + this.docInstanceId;
    try { localStorage.setItem(ptrKey, this.docInstanceId); } catch (e) {}
  };

  LegalDoc.prototype.persist = function () {
    try {
      localStorage.setItem(this.storageKey, JSON.stringify({
        docType: this.cfg.docType, docInstanceId: this.docInstanceId, context: this.context,
        fieldValues: this.values, tableData: this.tableData,
        signatures: this.signatures, lockedHash: this.lockedHash,
        savedAt: new Date().toISOString()
      }));
    } catch (e) {}
  };

  // Pull ledger-anchored signatures for this instance and reflect them locally so
  // a shared ?doc= link shows the signed/locked state on a device with no local
  // snapshot. Best-effort and offline-safe; never mints or posts anything.
  LegalDoc.prototype.loadFromRegistry = function () {
    var self = this;
    if (!this.docInstanceId) { this.finishHydration(); return; }
    fetch(API.registry + '?doc_id=' + encodeURIComponent(this.docInstanceId))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (data && Array.isArray(data.items) && data.items.length) {
          var active = self.activeAnchoredSignatures(data.items);
          var rids = Object.keys(active);
          // The ledger is authoritative for a shared link. Drop any locally cached
          // signature that is no longer active on the ledger — voided, or superseded
          // by a re-sign under a different content hash — so a voided or outdated
          // document never keeps appearing signed.
          Object.keys(self.signatures).forEach(function (rid) {
            var it = active[rid];
            if (!it || (it.document_hash && self.signatures[rid].documentHash &&
                        it.document_hash !== self.signatures[rid].documentHash)) {
              delete self.signatures[rid];
            }
          });
          if (rids.length) {
            rids.forEach(function (rid) {
              if (self.signatures[rid]) return; // keep a local signature (e.g. drawn ink)
              var it = active[rid];
              self.signatures[rid] = {
                role: it.role, party: '', signerName: it.signer_name || '',
                signerTitle: it.signer_title || '', method: it.signature_method || 'type',
                signatureData: '', signedAt: it.signed_at || '', documentHash: it.document_hash || '',
                receipt: { sequence_no: it.sequence_no, entry_hash: it.entry_hash, entry_id: it.entry_id }
              };
            });
            // Adopt the ledger's frozen content hash (all signatories share it) so a
            // re-signed document reflects the active anchored version, not stale local state.
            rids.forEach(function (rid) { if (active[rid].document_hash) self.lockedHash = active[rid].document_hash; });
            // Reconstruct the signed field/table content from the anchored
            // snapshot so the live hash matches lockedHash; this content exists
            // only server-side for a device with no local snapshot. Without it
            // the rendered defaults diverge from the signed hash and integrity
            // falsely reports tampering.
            self.hydrateContent(active, rids);
          } else {
            // Every anchor for this instance has been voided on the ledger — drop the
            // stale signed/locked state so the shared link no longer appears signed.
            self.lockedHash = null;
          }
          self.persist();
        }
        self.finishHydration();
      })
      .catch(function () { self.finishHydration(); });
  };

  // Restore the field values, table data and context that were anchored with a
  // signature so a shared ?doc= link renders the actual agreed document.
  LegalDoc.prototype.hydrateContent = function (active, rids) {
    var self = this;
    var snap = null;
    rids.forEach(function (rid) {
      var it = active[rid];
      if (!it || !it.content || typeof it.content !== 'object') return;
      // Prefer the snapshot that matches the frozen hash; all signatories attest
      // to the same content, but this guards against mixed/legacy entries.
      if (!snap || it.document_hash === self.lockedHash) snap = it.content;
    });
    if (!snap) return;
    if (snap.context) self.context = snap.context;
    if (snap.fieldValues && typeof snap.fieldValues === 'object') {
      self.values = Object.assign({}, self.values, snap.fieldValues);
    }
    if (snap.tableData && typeof snap.tableData === 'object') self.tableData = snap.tableData;
  };

  // Release the shared-link hydration lock and re-render with whatever signed
  // state (if any) was loaded. Runs on every completion path so the document
  // never stays stuck locked when the registry is empty or offline.
  LegalDoc.prototype.finishHydration = function () {
    this.hydrating = false;
    this.render();
    this.recompute();
    this.refreshIntegrity();
  };

  // Reduce raw registry events to the active signature per role, mirroring the
  // server verify() rule: a void only supersedes a signature when it carries a
  // strictly higher sequence number for the same (role, content hash).
  LegalDoc.prototype.activeAnchoredSignatures = function (items) {
    var self = this;
    var voidSeq = {};
    items.forEach(function (it) {
      if (it.event !== 'legal_document_voided' && !it.voided) return;
      var k = (it.role || '') + '|' + (it.document_hash || '');
      var seq = safeNum(it.sequence_no, 0);
      if (seq > (voidSeq[k] == null ? -1 : voidSeq[k])) voidSeq[k] = seq;
    });
    var active = {};
    items.forEach(function (it) {
      if (it.event !== 'legal_document_signed' || it.voided) return;
      var k = (it.role || '') + '|' + (it.document_hash || '');
      var seq = safeNum(it.sequence_no, 0);
      if (voidSeq[k] != null && voidSeq[k] > seq) return; // superseded by a later void
      var rid = self.sigRoleId({ role: it.role });
      var prev = active[rid];
      if (!prev || seq >= safeNum(prev.sequence_no, 0)) active[rid] = it;
    });
    return active;
  };

  LegalDoc.prototype.newCopy = function () {
    if (this.locked() && !confirm('Start a NEW blank copy? The current signed copy stays saved under its own ID.')) return;
    try { localStorage.removeItem('phins.legal.ptr.' + this.cfg.docType); } catch (e) {}
    var url = location.pathname;
    location.href = url; // fresh mint (no ?doc)
  };

  // ------------------------------------------------------------- rendering
  LegalDoc.prototype.render = function () {
    document.title = 'PHINS — ' + this.cfg.title;
    var root = $('#ld-root');
    root.innerHTML = '';

    root.appendChild(this.buildHeader());
    var shell = el('div', 'ld-shell');
    shell.appendChild(this.buildControls());
    shell.appendChild(this.buildDoc());
    root.appendChild(shell);

    if (!this.toast) {
      this.toast = el('div', 'ld-toast');
      document.body.appendChild(this.toast);
    }

    this.wireFields();
    this.applyContext();
    this.refreshBindings();
    this.renderSignatures();
  };

  LegalDoc.prototype.buildHeader = function () {
    var h = el('header', 'ld-header');
    h.innerHTML =
      '<div class="ld-logo-row"><div class="ld-logo-icon">🛡️</div>' +
      '<div><div class="ld-logo-text">PHINS</div>' +
      '<div class="ld-logo-tagline">Personal Health Insurance &amp; Savings</div></div></div>' +
      '<div class="ld-header-links">' +
      '<a class="ld-link" href="/corporate-legal-dashboard.html">← Legal &amp; Funding Center</a>' +
      '<a class="ld-link" href="/pitch-dashboard.html">📂 Investor Documents</a>' +
      '<a class="ld-link" href="/admin.html">← Admin</a>' +
      '</div>';
    return h;
  };

  LegalDoc.prototype.buildControls = function () {
    var self = this;
    var c = el('aside', 'ld-controls ld-no-print');
    c.appendChild(el('h2', null, '⚙️ Adjust this document'));
    c.appendChild(el('div', 'ld-sub', 'Edit the fields below — the document and signatures update live. Fields lock once the first signature is captured.'));

    // context selector
    if (this.contexts.length > 1) {
      var cf = el('div', 'ld-field ld-context-row');
      cf.appendChild(el('label', null, 'Document context / audience'));
      var sel = el('select');
      sel.id = 'ld-context-select';
      this.contexts.forEach(function (ctx) {
        var o = el('option'); o.value = ctx.id; o.textContent = ctx.label;
        if (ctx.id === self.context) o.selected = true;
        sel.appendChild(o);
      });
      sel.addEventListener('change', function () {
        if (self.locked()) { sel.value = self.context; self.flash('Locked after signature — void to change context.', 'err'); return; }
        self.context = sel.value; self.applyContext(); self.refreshBindings(); self.renderSignatures(); self.recompute(); self.persist();
      });
      cf.appendChild(sel);
      c.appendChild(cf);
    }

    // preset selector (role presets etc.)
    if (this.cfg.presets) {
      var p = this.cfg.presets;
      var pf = el('div', 'ld-field');
      pf.appendChild(el('label', null, p.label || 'Preset'));
      var psel = el('select'); psel.id = 'ld-preset-select';
      psel.appendChild(new Option('— select a preset —', ''));
      (p.options || []).forEach(function (opt) { psel.appendChild(new Option(opt.label, opt.id)); });
      psel.addEventListener('change', function () {
        if (self.locked()) { self.flash('Locked after signature.', 'err'); psel.value=''; return; }
        var opt = (p.options || []).filter(function (o) { return o.id === psel.value; })[0];
        if (!opt) return;
        Object.keys(opt.values).forEach(function (k) {
          self.values[k] = opt.values[k];
          var inp = $('#ldf-' + k);
          if (inp) inp.value = opt.values[k];
        });
        self.refreshBindings(); self.recompute(); self.persist();
        self.flash('Applied preset: ' + opt.label, 'ok');
      });
      if (p.hint) { var hh = el('div', 'ld-hint', p.hint); pf.appendChild(psel); pf.appendChild(hh); }
      else pf.appendChild(psel);
      c.appendChild(pf);
    }

    // fields (grouped)
    var groups = {};
    var order = [];
    this.fields.forEach(function (f) {
      var g = f.group || 'Details';
      if (!groups[g]) { groups[g] = []; order.push(g); }
      groups[g].push(f);
    });
    order.forEach(function (g) {
      var gt = el('div', 'ld-group-title', g);
      gt.setAttribute('data-field-group', g);
      c.appendChild(gt);
      groups[g].forEach(function (f) { c.appendChild(self.buildField(f)); });
    });

    // table editors
    this.tables.forEach(function (t) { if (t.editable !== false) c.appendChild(self.buildTableEditor(t)); });

    // action buttons
    var br = el('div', 'ld-btn-row');
    br.innerHTML =
      '<button class="ld-btn" id="ld-print">🖨️ Print / Save PDF</button>' +
      '<button class="ld-btn secondary" id="ld-verify">🔐 Verify integrity</button>' +
      '<button class="ld-btn ghost" id="ld-newcopy">🆕 New blank copy</button>';
    c.appendChild(br);
    var lock = el('div', 'ld-locknote', '🔒 This document is locked after signature to preserve integrity. Use “Unlock &amp; void” below to invalidate signatures and edit again.');
    lock.id = 'ld-locknote';
    c.appendChild(lock);
    var vr = el('div', 'ld-btn-row');
    vr.innerHTML = '<button class="ld-btn danger" id="ld-void" style="display:none;">🗑️ Unlock &amp; void signatures</button>';
    c.appendChild(vr);
    return c;
  };

  LegalDoc.prototype.buildField = function (f) {
    var w = el('div', 'ld-field');
    w.setAttribute('data-field', f.key);
    if (f.context) w.setAttribute('data-field-context', f.context);
    w.appendChild(el('label', null, esc(f.label)));
    var input;
    if (f.type === 'select') {
      input = el('select');
      (f.options || []).forEach(function (o) {
        var ov = typeof o === 'string' ? o : o.value;
        var ol = typeof o === 'string' ? o : o.label;
        var opt = new Option(ol, ov);
        input.appendChild(opt);
      });
    } else if (f.type === 'textarea') {
      input = el('textarea');
    } else {
      input = el('input');
      input.type = (f.type === 'number' || f.type === 'currency' || f.type === 'percent') ? 'number'
        : (f.type === 'date' ? 'date' : 'text');
      if (f.type === 'percent') { input.step = '0.01'; }
      if (f.type === 'currency') { input.step = '0.01'; }
    }
    input.id = 'ldf-' + f.key;
    input.value = this.values[f.key] != null ? this.values[f.key] : '';
    w.appendChild(input);
    if (f.hint) w.appendChild(el('div', 'ld-hint', esc(f.hint)));
    return w;
  };

  LegalDoc.prototype.buildTableEditor = function (t) {
    var self = this;
    var w = el('div');
    w.appendChild(el('div', 'ld-group-title', (t.title || t.key) + ' — rows'));
    var add = el('button', 'ld-btn secondary', '＋ Add row');
    add.style.fontSize = '8pt'; add.style.padding = '6px 11px';
    add.addEventListener('click', function () {
      if (self.locked()) { self.flash('Locked after signature.', 'err'); return; }
      var blank = {}; (t.columns || []).forEach(function (col) { blank[col.key] = ''; });
      self.tableData[t.key].push(blank);
      self.refreshTable(t); self.recompute(); self.persist();
    });
    w.appendChild(add);
    return w;
  };

  // -------------------------------------------------------------- document
  LegalDoc.prototype.buildDoc = function () {
    var self = this;
    var wrap = el('div', 'ld-doc-wrap');

    // disclaimer
    wrap.appendChild(el('div', 'ld-disclaimer',
      '<strong>Template — not legal advice.</strong> This is an adjustable PHINS document template for ' +
      'negotiation and internal preparation only. It is not an executed instrument and should be reviewed ' +
      'by qualified counsel in the relevant jurisdiction before use. Figures shown are editable defaults.'));

    var page = el('section', 'ld-page');

    // head
    var head = el('div', 'ld-doc-head');
    head.innerHTML =
      '<div class="brand"><div class="icon">🛡️</div><div>' +
      '<div class="name">PHINS</div><div class="tag">Personal Health Insurance &amp; Savings</div></div></div>' +
      '<div class="ld-doc-ref"><span class="badge">' + esc(this.cfg.refLabel || 'CORPORATE DOCUMENT') + '</span><br>' +
      'Ref: <span data-bind="__docid">' + esc(this.docInstanceId) + '</span><br>' +
      'Context: <span data-bind="__context">' + esc(this.context) + '</span></div>';
    page.appendChild(head);

    page.appendChild(el('div', 'ld-doc-title', esc(this.cfg.title)));
    if (this.cfg.subtitle) page.appendChild(el('div', 'ld-doc-subtitle', this.cfg.subtitle));

    // body
    var body = el('div', 'ld-body');
    body.innerHTML = this.expandBody(this.cfg.body || '');
    page.appendChild(body);
    this.bodyEl = body;

    // place tables
    this.tables.forEach(function (t) {
      var mount = body.querySelector('[data-table="' + t.key + '"]') ;
      if (!mount) { mount = el('div'); mount.setAttribute('data-table', t.key); body.appendChild(mount); }
    });

    // signatures mount
    var sigWrap = el('div', 'ld-sign-wrap');
    sigWrap.id = 'ld-sign-wrap';
    page.appendChild(sigWrap);

    // integrity footer
    var integ = el('div', 'ld-integrity'); integ.id = 'ld-integrity';
    page.appendChild(integ);

    wrap.appendChild(page);
    return wrap;
  };

  // turn {{key}} into bind spans; {{table:key}} into table mounts
  LegalDoc.prototype.expandBody = function (html) {
    return html.replace(/\{\{\s*table:([\w.-]+)\s*\}\}/g, function (m, key) {
      return '<div data-table="' + key + '"></div>';
    }).replace(/\{\{\s*html:([\w.-]+)\s*\}\}/g, function (m, key) {
      // engine-generated HTML (e.g. computed projection tables); compute() must
      // escape any user-supplied text — only numeric/derived output goes here.
      return '<div data-bindhtml="' + key + '"></div>';
    }).replace(/\{\{\s*([\w.+-]+)\s*\}\}/g, function (m, key) {
      return '<span class="ld-bind" data-bind="' + key + '"></span>';
    });
  };

  LegalDoc.prototype.wireFields = function () {
    var self = this;
    this.fields.forEach(function (f) {
      var inp = $('#ldf-' + f.key);
      if (!inp) return;
      var ev = (f.type === 'select' || f.type === 'date') ? 'change' : 'input';
      inp.addEventListener(ev, function () {
        if (self.locked()) { inp.value = self.values[f.key]; self.flash('Locked after signature.', 'err'); return; }
        self.values[f.key] = inp.value;
        self.refreshBindings(); self.recompute(); self.persist();
      });
    });
    $('#ld-print').addEventListener('click', function () { window.print(); });
    $('#ld-newcopy').addEventListener('click', function () { self.newCopy(); });
    $('#ld-verify').addEventListener('click', function () { self.verify(); });
    var voidBtn = $('#ld-void');
    if (voidBtn) voidBtn.addEventListener('click', function () { self.voidSignatures(); });
    // initial tables
    this.tables.forEach(function (t) { self.refreshTable(t); });
    this.applyLockUI();
  };

  LegalDoc.prototype.applyContext = function () {
    var self = this;
    // toggle context blocks
    Array.prototype.forEach.call(document.querySelectorAll('[data-context-block]'), function (n) {
      var allow = n.getAttribute('data-context-block').split(',').map(function (s) { return s.trim(); });
      n.classList.toggle('active', allow.indexOf(self.context) >= 0 || allow.indexOf('*') >= 0);
    });
    // toggle field controls by context
    Array.prototype.forEach.call(document.querySelectorAll('[data-field-context]'), function (n) {
      var allow = n.getAttribute('data-field-context').split(',').map(function (s) { return s.trim(); });
      n.style.display = (allow.indexOf(self.context) >= 0) ? '' : 'none';
    });
    var cb = $('[data-bind="__context"]');
    var label = (this.contexts.filter(function (c) { return c.id === self.context; })[0] || {}).label || this.context;
    if (cb) cb.textContent = label;
  };

  LegalDoc.prototype.fieldType = function (key) {
    var f = this.fields.filter(function (x) { return x.key === key; })[0];
    return f ? f.type : 'text';
  };

  LegalDoc.prototype.refreshBindings = function () {
    var self = this;
    var merged = Object.assign({}, this.values, this.derived || {});
    // engine-generated HTML bindings (computed tables) — innerHTML, trusted output
    Array.prototype.forEach.call(document.querySelectorAll('[data-bindhtml]'), function (n) {
      var key = n.getAttribute('data-bindhtml');
      var val = merged[key];
      var html = (val && typeof val === 'object' && 'display' in val) ? val.display : (val || '');
      n.innerHTML = html || '';
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-bind]'), function (n) {
      var key = n.getAttribute('data-bind');
      if (key === '__docid') { n.textContent = self.docInstanceId; return; }
      if (key === '__context') return;
      var val = merged[key];
      var type = self.fieldType(key);
      // derived may carry its own formatting via {key: {display}}
      var display;
      if (val && typeof val === 'object' && 'display' in val) display = val.display;
      else display = fmt(val, type, self.values.currency);
      if (display === '' || display == null) {
        n.textContent = self.placeholderFor(key); n.classList.add('empty');
      } else { n.textContent = display; n.classList.remove('empty'); }
    });
  };

  LegalDoc.prototype.placeholderFor = function (key) {
    var f = this.fields.filter(function (x) { return x.key === key; })[0];
    return f ? ('[' + (f.label || key) + ']') : ('[' + key + ']');
  };

  LegalDoc.prototype.recompute = function () {
    if (typeof this.cfg.compute === 'function') {
      try { this.derived = this.cfg.compute(Object.assign({}, this.values), this) || {}; }
      catch (e) { this.derived = {}; }
    } else { this.derived = {}; }
    this.refreshBindings();
    // recompute table computed cells + footers
    var self = this;
    this.tables.forEach(function (t) {
      self.refreshComputedCells(t);
      if (t.computeFooter) self.refreshTableFooter(t);
    });
  };

  // ---------------------------------------------------------------- tables
  LegalDoc.prototype.refreshTable = function (t) {
    var self = this;
    var mount = this.bodyEl ? this.bodyEl.querySelector('[data-table="' + t.key + '"]') : null;
    if (!mount) return;
    var rows = this.tableData[t.key] || [];
    var html = '<table class="ld-table"><thead><tr>';
    (t.columns || []).forEach(function (c) { html += '<th' + (c.num ? ' class="num"' : '') + '>' + esc(c.label) + '</th>'; });
    if (t.editable !== false) html += '<th class="ld-no-print"></th>';
    html += '</tr></thead><tbody>';
    rows.forEach(function (row, i) {
      html += '<tr>';
      (t.columns || []).forEach(function (c) {
        var v = row[c.key] != null ? row[c.key] : '';
        if (c.computed) {
          html += '<td class="num" data-cell="' + t.key + ':' + i + ':' + c.key + '">' + esc(self.computedCell(t, row, c)) + '</td>';
        } else if (t.editable !== false) {
          html += '<td' + (c.num ? ' class="num"' : '') + '><input data-tin="' + t.key + ':' + i + ':' + c.key + '" ' +
            'type="' + (c.type === 'number' || c.type === 'currency' || c.type === 'percent' ? 'number' : 'text') + '" ' +
            'value="' + esc(v) + '"></td>';
        } else {
          html += '<td' + (c.num ? ' class="num"' : '') + '>' + esc(v) + '</td>';
        }
      });
      if (t.editable !== false) html += '<td class="ld-no-print"><button class="ld-row-del" data-tdel="' + t.key + ':' + i + '">×</button></td>';
      html += '</tr>';
    });
    html += '</tbody>';
    if (t.computeFooter) html += '<tfoot data-tfoot="' + t.key + '"></tfoot>';
    html += '</table>';
    mount.innerHTML = html;

    // wire inputs
    Array.prototype.forEach.call(mount.querySelectorAll('[data-tin]'), function (inp) {
      inp.disabled = self.locked();
      inp.addEventListener('input', function () {
        var parts = inp.getAttribute('data-tin').split(':');
        self.tableData[parts[0]][parts[1]][parts[2]] = inp.value;
        self.recompute(); self.refreshComputedCells(t); self.persist();
      });
    });
    Array.prototype.forEach.call(mount.querySelectorAll('[data-tdel]'), function (b) {
      b.addEventListener('click', function () {
        if (self.locked()) { self.flash('Locked after signature.', 'err'); return; }
        var parts = b.getAttribute('data-tdel').split(':');
        self.tableData[parts[0]].splice(parts[1], 1);
        self.refreshTable(t); self.recompute(); self.persist();
      });
    });
    this.refreshTableFooter(t);
  };

  LegalDoc.prototype.computedCell = function (t, row, c) {
    try { return c.computed(row, this.derived || {}, this); } catch (e) { return ''; }
  };
  LegalDoc.prototype.refreshComputedCells = function (t) {
    var self = this, rows = this.tableData[t.key] || [];
    (t.columns || []).forEach(function (c) {
      if (!c.computed) return;
      rows.forEach(function (row, i) {
        var cell = self.bodyEl.querySelector('[data-cell="' + t.key + ':' + i + ':' + c.key + '"]');
        if (cell) cell.textContent = self.computedCell(t, row, c);
      });
    });
  };
  LegalDoc.prototype.refreshTableFooter = function (t) {
    if (!t.computeFooter || !this.bodyEl) return;
    var tf = this.bodyEl.querySelector('[data-tfoot="' + t.key + '"]');
    if (!tf) return;
    try { tf.innerHTML = t.computeFooter(this.tableData[t.key] || [], this.derived || {}, this); }
    catch (e) { tf.innerHTML = ''; }
  };

  // ------------------------------------------------------------ signatures
  LegalDoc.prototype.activeSignatories = function () {
    var self = this;
    return this.signatories.filter(function (s) {
      if (!s.context) return true;
      return s.context.split(',').map(function (x) { return x.trim(); }).indexOf(self.context) >= 0;
    });
  };

  LegalDoc.prototype.renderSignatures = function () {
    var self = this;
    var wrap = $('#ld-sign-wrap');
    if (!wrap) return;
    var sigs = this.activeSignatories();
    var html = '<h2>✍️ Signatures</h2>' +
      '<div class="ld-sign-intro">Each party signs below (draw or type). On signing, the signature, signer, and ' +
      'date/time are locked and the document content hash is anchored to the PHINS tamper-evident ledger.</div>' +
      '<div class="ld-sign-grid">';
    sigs.forEach(function (s) {
      var rid = self.sigRoleId(s);
      var party = self.resolveParty(s);
      var sig = self.signatures[rid];
      html += '<div class="ld-sig-panel' + (sig ? ' signed' : '') + '" data-sigpanel="' + esc(rid) + '">' +
        '<span class="ld-sig-badge ' + (sig ? 'signed' : 'unsigned') + '">' + (sig ? 'Signed' : 'Unsigned') + '</span>' +
        '<div class="ld-sig-role">' + esc(s.role) + '</div>' +
        '<div class="ld-sig-party">' + esc(party) + '</div>' +
        '<div class="ld-sig-editor">' +
          '<div class="ld-sig-mode-row">' +
            '<button class="ld-btn" data-sigmode="draw" aria-pressed="true">✏️ Draw</button>' +
            '<button class="ld-btn" data-sigmode="type" aria-pressed="false">⌨️ Type</button>' +
          '</div>' +
          '<div class="ld-sig-pad-box" data-sigdraw>' +
            '<canvas class="ld-sig-pad" width="520" height="110"></canvas>' +
            '<button class="ld-btn ghost ld-sig-clear" data-sigclear>↺ Clear</button>' +
          '</div>' +
          '<div data-sigtype style="display:none;">' +
            '<input class="ld-sig-typed-input" data-sigtyped placeholder="Type full name to sign">' +
          '</div>' +
          '<div class="ld-sig-meta">' +
            '<div class="ld-field"><label>Signer name</label><input data-signame placeholder="Full legal name"></div>' +
            '<div class="ld-field"><label>Title (optional)</label><input data-sigtitle placeholder="Title / capacity"></div>' +
          '</div>' +
          '<div class="ld-sig-actions"><button class="ld-btn" data-sigcommit>🔏 Sign &amp; lock</button></div>' +
        '</div>' +
        '<div class="ld-sig-result"></div>' +
      '</div>';
    });
    html += '</div>';
    wrap.innerHTML = html;

    sigs.forEach(function (s) {
      var rid = self.sigRoleId(s);
      var panel = wrap.querySelector('[data-sigpanel="' + cssEsc(rid) + '"]');
      if (!panel) return;
      if (self.signatures[rid]) { self.renderSignedPanel(panel, rid); }
      else { self.wireSigPanel(panel, s, rid); }
    });
    this.applyLockUI();
  };

  LegalDoc.prototype.sigRoleId = function (s) { return (s.role || 'party').toLowerCase().replace(/[^a-z0-9]+/g, '-'); };

  LegalDoc.prototype.resolveParty = function (s) {
    // party can be a literal or reference a field via {{key}}
    var self = this;
    var p = s.party || '';
    return p.replace(/\{\{\s*([\w.-]+)\s*\}\}/g, function (m, key) {
      var v = self.values[key];
      return (v != null && v !== '') ? v : '[' + key + ']';
    });
  };

  LegalDoc.prototype.wireSigPanel = function (panel, s, rid) {
    var self = this;
    var canvas = panel.querySelector('.ld-sig-pad');
    var ctx = canvas.getContext('2d');
    var drawn = false, drawing = false;
    function pos(e) {
      var r = canvas.getBoundingClientRect();
      var cx = (e.touches ? e.touches[0].clientX : e.clientX) - r.left;
      var cy = (e.touches ? e.touches[0].clientY : e.clientY) - r.top;
      return { x: cx * (canvas.width / r.width), y: cy * (canvas.height / r.height) };
    }
    function start(e) { drawing = true; var p = pos(e); ctx.beginPath(); ctx.moveTo(p.x, p.y); e.preventDefault(); }
    function move(e) { if (!drawing) return; var p = pos(e); ctx.lineWidth = 2.2; ctx.lineCap = 'round'; ctx.strokeStyle = '#0d2a5c'; ctx.lineTo(p.x, p.y); ctx.stroke(); drawn = true; e.preventDefault(); }
    function end() { drawing = false; }
    canvas.addEventListener('mousedown', start); canvas.addEventListener('mousemove', move);
    window.addEventListener('mouseup', end);
    canvas.addEventListener('touchstart', start, { passive: false });
    canvas.addEventListener('touchmove', move, { passive: false });
    canvas.addEventListener('touchend', end);
    panel._hasInk = function () { return drawn; };

    var mode = 'draw';
    var drawBtn = panel.querySelector('[data-sigmode="draw"]');
    var typeBtn = panel.querySelector('[data-sigmode="type"]');
    drawBtn.addEventListener('click', function () {
      mode = 'draw'; drawBtn.setAttribute('aria-pressed', 'true'); typeBtn.setAttribute('aria-pressed', 'false');
      panel.querySelector('[data-sigdraw]').style.display = ''; panel.querySelector('[data-sigtype]').style.display = 'none';
    });
    typeBtn.addEventListener('click', function () {
      mode = 'type'; typeBtn.setAttribute('aria-pressed', 'true'); drawBtn.setAttribute('aria-pressed', 'false');
      panel.querySelector('[data-sigdraw]').style.display = 'none'; panel.querySelector('[data-sigtype]').style.display = '';
    });
    panel.querySelector('[data-sigclear]').addEventListener('click', function () {
      ctx.clearRect(0, 0, canvas.width, canvas.height); drawn = false;
    });
    panel.querySelector('[data-sigcommit]').addEventListener('click', function () {
      self.commitSignature(panel, s, rid, mode, canvas);
    });
  };

  LegalDoc.prototype.contentState = function () {
    // signatures intentionally EXCLUDED so all signatories attest to the same hash
    return {
      docType: this.cfg.docType,
      docInstanceId: this.docInstanceId,
      context: this.context,
      fields: this.activeFieldValues(),
      derived: stripDisplay(this.derived || {}),
      tables: this.tableData
    };
  };
  // Only the fields visible in the active context contribute to the signed hash.
  // Fields hidden by data-field-context (e.g. co-founder B/C on a solo-founder
  // agreement) are not part of the rendered document, so their defaults must not
  // change the digest signers attest to.
  LegalDoc.prototype.activeFieldValues = function () {
    var self = this;
    var out = {};
    this.fields.forEach(function (f) {
      if (f.context) {
        var allow = f.context.split(',').map(function (s) { return s.trim(); });
        if (allow.indexOf(self.context) < 0) return;
      }
      if (self.values[f.key] !== undefined) out[f.key] = self.values[f.key];
    });
    return out;
  };
  function stripDisplay(d) {
    var out = {};
    Object.keys(d).forEach(function (k) {
      var v = d[k];
      out[k] = (v && typeof v === 'object' && 'value' in v) ? v.value : v;
    });
    return out;
  }

  LegalDoc.prototype.commitSignature = function (panel, s, rid, mode, canvas) {
    var self = this;
    // Block signing until a shared link finishes loading anchored state, so a
    // new signature can't be captured over content that doesn't yet match the
    // already-anchored document hash.
    if (this.hydrating) { this.flash('Loading the signed document — please wait…', 'err'); return; }
    var name = (panel.querySelector('[data-signame]').value || '').trim();
    var title = (panel.querySelector('[data-sigtitle]').value || '').trim();
    var typed = (panel.querySelector('[data-sigtyped]').value || '').trim();
    if (!name) { this.flash('Enter the signer name before signing.', 'err'); return; }
    if (mode === 'draw' && !(panel._hasInk && panel._hasInk())) { this.flash('Draw a signature, or switch to Type.', 'err'); return; }
    if (mode === 'type' && !typed) { this.flash('Type the signature, or switch to Draw.', 'err'); return; }

    var signatureData = mode === 'draw' ? canvas.toDataURL('image/png') : typed;
    var signedAt = new Date().toISOString();

    // Lock editing synchronously the moment Sign is clicked, so edits made while
    // the hash is computing asynchronously cannot mutate the live document.
    this.locking = true;
    this.applyLockUI();

    // Freeze the content hash on the FIRST signature. Later signers re-hash the
    // live content and must match the frozen hash, so every signatory attests to
    // identical content (e.g. if registry hydration did not restore the anchored
    // snapshot). A mismatch blocks the signature rather than anchoring stale content.
    sha256Hex(stableStringify(this.contentState())).then(function (liveHash) {
      if (self.lockedHash && liveHash !== self.lockedHash) {
        self.locking = false;
        self.applyLockUI();
        self.flash('Document content no longer matches the hash signed by earlier parties — reload the anchored version before signing.', 'err');
        return;
      }
      var docHash = self.lockedHash || liveHash;
      self.lockedHash = docHash;
      self.signatures[rid] = {
        role: s.role, party: self.resolveParty(s), signerName: name, signerTitle: title,
        method: mode, signatureData: signatureData, signedAt: signedAt,
        documentHash: docHash, receipt: null
      };
      self.applyLockUI();
      self.renderSignedPanel(panel, rid);
      self.persist();
      self.recompute();
      self.refreshIntegrity();
      self.flash('Signed by ' + name + '. Anchoring to ledger…', 'ok');
      self.anchor(rid);
    });
  };

  LegalDoc.prototype.anchor = function (rid) {
    var self = this;
    var sig = this.signatures[rid];
    if (!sig) return;
    postJSON(API.sign, {
      docType: this.cfg.docType, docInstanceId: this.docInstanceId, context: this.context,
      role: sig.role, signerName: sig.signerName, signerTitle: sig.signerTitle,
      signedAt: sig.signedAt, documentHash: sig.documentHash, signatureMethod: sig.method,
      // Persist the exact signed content so a counterparty opening the shared
      // ?doc= link on another device renders the document the hash attests to.
      // Use the same context-filtered field set that fed the signed hash, so two
      // parties sharing a hash anchor identical snapshots instead of hitting the
      // server's content-conflict guard over hidden/default keys in this.values.
      content: { context: this.context, fieldValues: this.activeFieldValues(), tableData: this.tableData }
    }).then(function (res) {
      if (res.ok && res.data && res.data.entry_hash) {
        sig.receipt = { sequence_no: res.data.sequence_no, entry_hash: res.data.entry_hash, entry_id: res.data.entry_id };
        self.persist();
        var panel = $('[data-sigpanel="' + cssEsc(rid) + '"]');
        if (panel) self.renderSignedPanel(panel, rid);
        self.refreshIntegrity();
      } else if (res.data && res.data.error) {
        // The ledger definitively rejected this anchor (e.g. content conflict or
        // validation), not a transient outage. Roll back the local signature so
        // the UI doesn't keep showing a signed/locked document for a party that
        // has no active anchor on the append-only ledger. If this was the only
        // signature, clear the frozen hash and unlock editing again.
        delete self.signatures[rid];
        if (Object.keys(self.signatures).length === 0) {
          self.lockedHash = null;
          self.locking = false;
        }
        self.persist();
        self.renderSignatures();
        self.recompute();
        self.refreshIntegrity();
        self.flash('Anchor rejected: ' + res.data.error + ' — signature was not applied.', 'err');
      } else {
        self.markAnchorPending(rid);
      }
    }).catch(function () { self.markAnchorPending(rid); });
  };

  LegalDoc.prototype.markAnchorPending = function (rid) {
    var panel = $('[data-sigpanel="' + cssEsc(rid) + '"]');
    if (panel) this.renderSignedPanel(panel, rid, true);
  };

  LegalDoc.prototype.renderSignedPanel = function (panel, rid, pending) {
    var self = this;
    var sig = this.signatures[rid];
    if (!sig) return;
    panel.classList.add('signed');
    var badge = panel.querySelector('.ld-sig-badge');
    if (badge) { badge.className = 'ld-sig-badge signed'; badge.textContent = 'Signed'; }
    var dateStr = new Date(sig.signedAt).toLocaleString(undefined, {
      year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZoneName: 'short'
    });
    var sigHtml;
    if (!sig.signatureData) {
      // Anchored on another device — the signature mark isn't stored server-side,
      // so attest to the signer by name instead of rendering a broken image.
      sigHtml = '<span class="typed">' + esc(sig.signerName || 'Signed') + '</span>';
    } else if (sig.method === 'draw') {
      sigHtml = '<img alt="signature" src="' + sig.signatureData + '">';
    } else {
      sigHtml = '<span class="typed">' + esc(sig.signatureData) + '</span>';
    }
    var receipt;
    if (sig.receipt) {
      receipt = '<div class="ld-sig-receipt"><span class="ok">✔ Anchored to PHINS ledger</span><br>' +
        'seq #' + esc(sig.receipt.sequence_no) + ' · entry ' + esc((sig.receipt.entry_hash || '').slice(0, 24)) + '…<br>' +
        'content hash ' + esc((sig.documentHash || '').slice(0, 24)) + '…</div>';
    } else {
      receipt = '<div class="ld-sig-receipt"><span class="pending">⏳ Anchor pending (offline / retry)</span><br>' +
        'content hash ' + esc((sig.documentHash || '').slice(0, 24)) + '…' +
        ' <button class="ld-btn ghost ld-no-print" data-sigretry style="font-size:7.5pt;padding:3px 8px;">Retry anchor</button></div>';
    }
    var res = panel.querySelector('.ld-sig-result');
    res.innerHTML =
      '<div class="ld-sig-rendered">' + sigHtml + '</div>' +
      '<div class="ld-sig-name">' + esc(sig.signerName) + '</div>' +
      (sig.signerTitle ? '<div class="ld-sig-title">' + esc(sig.signerTitle) + '</div>' : '') +
      '<div class="ld-sig-date">Signed on <strong>' + esc(dateStr) + '</strong></div>' +
      receipt;
    var retry = res.querySelector('[data-sigretry]');
    if (retry) retry.addEventListener('click', function () { self.flash('Retrying anchor…', 'ok'); self.anchor(rid); });
  };

  LegalDoc.prototype.applyLockUI = function () {
    var locked = this.locked();
    var note = $('#ld-locknote'); if (note) note.classList.toggle('show', locked);
    var voidBtn = $('#ld-void'); if (voidBtn) voidBtn.style.display = locked ? '' : 'none';
    // disable field inputs
    this.fields.forEach(function (f) { var i = $('#ldf-' + f.key); if (i) i.disabled = locked; });
    var ctxSel = $('#ld-context-select'); if (ctxSel) ctxSel.disabled = locked;
    var preSel = $('#ld-preset-select'); if (preSel) preSel.disabled = locked;
    Array.prototype.forEach.call(document.querySelectorAll('[data-tin]'), function (i) { i.disabled = locked; });
  };

  LegalDoc.prototype.voidSignatures = function () {
    if (!confirm('Void ALL signatures on this document? This records a void event in the ledger and unlocks editing. This cannot be undone.')) return;
    var self = this;
    var roles = Object.keys(this.signatures);
    // Anchor every void to the ledger BEFORE clearing local state. Editing must
    // not resume (and the UI must not claim "voided") until the ledger confirms,
    // otherwise prior signatures stay active server-side while the UI looks
    // unsigned, letting a user re-sign over still-active anchors.
    var voids = roles.map(function (rid) {
      var sig = self.signatures[rid];
      return postJSON(API.sign, {
        docType: self.cfg.docType, docInstanceId: self.docInstanceId, context: self.context,
        role: sig.role, signerName: sig.signerName, signedAt: new Date().toISOString(),
        documentHash: sig.documentHash, event: 'void'
      }).then(function (res) {
        return { rid: rid, ok: !!(res.ok && res.data && res.data.entry_hash) };
      }).catch(function () {
        return { rid: rid, ok: false };
      });
    });
    this.flash('Voiding signatures…', 'ok');
    // Reconcile per-role: drop only the signatures whose void actually anchored.
    // If some voids fail, those signatures stay active server-side, so they must
    // remain locally too (document stays locked) instead of clearing everything
    // on an all-or-nothing basis — which would desync the UI from the ledger.
    Promise.all(voids).then(function (results) {
      var failed = 0;
      results.forEach(function (r) {
        if (r.ok) { delete self.signatures[r.rid]; }
        else { failed++; }
      });
      if (Object.keys(self.signatures).length === 0) {
        self.lockedHash = null;
        self.locking = false;
      }
      self.persist();
      self.applyLockUI();
      self.renderSignatures();
      self.recompute();
      self.refreshIntegrity();
      if (failed) {
        self.flash(failed + ' of ' + results.length + ' voids failed to anchor — those signatures remain active. Check your connection and retry.', 'err');
      } else {
        self.flash('Signatures voided. Document unlocked.', 'ok');
      }
    });
  };

  // ------------------------------------------------------------- integrity
  LegalDoc.prototype.refreshIntegrity = function () {
    var self = this;
    var box = $('#ld-integrity'); if (!box) return;
    var signed = Object.keys(this.signatures).length;
    var total = this.activeSignatories().length;
    sha256Hex(stableStringify(this.contentState())).then(function (live) {
      var tamper = self.lockedHash && live !== self.lockedHash;
      var statusHtml = self.lockedHash
        ? (tamper
            ? '<span class="v-bad">⚠ CONTENT CHANGED since signing — signatures no longer match this content.</span>'
            : '<span class="v-ok">✔ Content matches the hash signed by all parties.</span>')
        : 'Unsigned draft — content hash is provisional and will be frozen at first signature.';
      box.innerHTML =
        '<strong>Data integrity</strong> — Document instance <code>' + esc(self.docInstanceId) + '</code>. ' +
        'Signatures: ' + signed + ' of ' + total + '. ' + statusHtml + '<br>' +
        'Current content SHA-256: <code>' + esc(live) + '</code>' +
        (self.lockedHash ? '<br>Signed content SHA-256: <code>' + esc(self.lockedHash) + '</code>' : '') +
        '<br><span class="ld-no-print">This document and every signature are anchored append-only into the PHINS ' +
        'hash-chained platform event ledger (tamper-evident). AI/automation may recommend but never sign or post.</span>';
      // reflect tamper on panels
      Array.prototype.forEach.call(document.querySelectorAll('.ld-sig-panel.signed'), function (p) {
        p.classList.toggle('tampered', !!tamper);
        var b = p.querySelector('.ld-sig-badge');
        if (b) { b.className = 'ld-sig-badge ' + (tamper ? 'tampered' : 'signed'); b.textContent = tamper ? 'Tampered' : 'Signed'; }
      });
    });
  };

  LegalDoc.prototype.verify = function () {
    var self = this;
    if (!this.lockedHash) { this.flash('Nothing signed yet to verify.', 'err'); return; }
    sha256Hex(stableStringify(this.contentState())).then(function (live) {
      postJSON(API.verify, { docInstanceId: self.docInstanceId, documentHash: self.lockedHash })
        .then(function (res) {
          var d = res.data || {};
          var localMatch = live === self.lockedHash;
          if (d.verified && d.chain_valid && localMatch) {
            self.flash('✔ Verified: content unchanged, anchored, and ledger chain intact.', 'ok');
          } else if (!localMatch) {
            self.flash('⚠ Local content changed since signing — does not match the signed hash.', 'err');
          } else if (!d.verified) {
            self.flash('⚠ No matching anchor found on the ledger yet (anchor may be pending).', 'err');
          } else {
            self.flash('⚠ Ledger chain reported issues — contact an administrator.', 'err');
          }
          self.refreshIntegrity();
        }).catch(function () {
          self.flash(live === self.lockedHash ? 'Offline: local content matches the signed hash.' : 'Offline: local content CHANGED since signing.',
            live === self.lockedHash ? 'ok' : 'err');
        });
    });
  };

  LegalDoc.prototype.flash = function (msg, kind) {
    if (!this.toast) return;
    this.toast.textContent = msg;
    this.toast.className = 'ld-toast show ' + (kind || '');
    clearTimeout(this._t);
    var self = this;
    this._t = setTimeout(function () { self.toast.className = 'ld-toast ' + (kind || ''); }, 3200);
  };

  // ------------------------------------------------------------------- API
  window.PhinsLegalDoc = {
    init: function (cfg) {
      function go() {
        if (!document.getElementById('ld-root')) {
          var r = document.createElement('div'); r.id = 'ld-root'; document.body.appendChild(r);
        }
        var inst = new LegalDoc(cfg);
        window.__phinsLegalDoc = inst;
        inst.boot();
      }
      if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', go);
      else go();
    }
  };
})();
