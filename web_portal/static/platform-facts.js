/**
 * Live platform facts for investor / partner surfaces.
 *
 * Fetches GET /api/platform/facts and fills:
 *   [data-live-modules]  — deployed services/*.py count
 *   [data-live="…"]      — canonical IL book (eoy, avg, gwp, NR, EBITDA, take)
 *
 * Fallback text in the HTML is the last-known identity so print / no-JS still
 * shows a number. Re-applies after i18n / legal-doc re-renders.
 */
(function (global) {
  "use strict";

  var FALLBACK_MODULES = 101;
  var facts = {
    service_modules: FALLBACK_MODULES,
    investor_book: null,
    source: "fallback"
  };
  var applying = false;

  function modules(fallback) {
    var n = facts.service_modules;
    return (typeof n === "number" && n > 0) ? n : (fallback || FALLBACK_MODULES);
  }

  function fmtInt(n) {
    return Math.round(Number(n)).toLocaleString("en-US");
  }

  function fmtPctFromRate(t) {
    var pct = Number(t) * 100;
    if (!isFinite(pct)) return null;
    return (Math.abs(pct - Math.round(pct)) < 0.05) ? (Math.round(pct) + "%") : (pct.toFixed(1) + "%");
  }

  function fmtM(n) {
    var v = Number(n);
    if (!isFinite(v)) return null;
    var neg = v < 0;
    var m = Math.abs(v) / 1e6;
    var s = m.toFixed(1);
    return (neg ? "(" + s + ")" : s) + "M";
  }

  function fmtIlsM(n, decimals) {
    var v = Number(n);
    if (!isFinite(v)) return null;
    var m = Math.abs(v) / 1e6;
    var dp = decimals == null ? 1 : decimals;
    var s = m.toFixed(dp);
    return (v < 0 ? "−₪" : "₪") + s + "M";
  }

  function bookAt(book, key, i) {
    if (!book) return null;
    var arr = book[key];
    if (Array.isArray(arr) && i != null && !isNaN(i)) return arr[i];
    return book[key];
  }

  function fillEl(el, text) {
    if (!el || text == null) return;
    var next = String(text);
    if (el.textContent !== next) el.textContent = next;
  }

  function applyModules(root) {
    var n = String(modules());
    var nodes = (root || document).querySelectorAll("[data-live-modules]");
    for (var i = 0; i < nodes.length; i++) fillEl(nodes[i], n);
  }

  function applyBook(root) {
    var book = facts.investor_book;
    if (!book) return;
    var nodes = (root || document).querySelectorAll("[data-live]");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var key = el.getAttribute("data-live");
      var idxAttr = el.getAttribute("data-i");
      var iNum = (idxAttr == null || idxAttr === "") ? null : Number(idxAttr);
      var text = null;
      if (key === "eoy") text = fmtInt(bookAt(book, "eoy_in_force", iNum));
      else if (key === "avg") text = fmtInt(bookAt(book, "avg_in_force", iNum));
      else if (key === "gwp_m") text = fmtM(bookAt(book, "gwp", iNum));
      else if (key === "nr_m") text = fmtM(bookAt(book, "net_revenue", iNum));
      else if (key === "ebitda_m") text = fmtM(bookAt(book, "ebitda", iNum));
      else if (key === "opex_m") text = fmtM(bookAt(book, "opex", iNum));
      else if (key === "take_pct") text = fmtPctFromRate(book.take_rate);
      else if (key === "premium") text = fmtInt(book.premium);
      else if (key === "nr_2029") text = fmtIlsM(book.net_revenue && book.net_revenue[2]);
      else if (key === "ebitda_margin_2029") {
        var m = book.ebitda_margin_2029;
        text = (m == null || !isFinite(Number(m))) ? null : (Math.round(Number(m) * 100) + "%");
      } else if (key === "seed_m") text = fmtIlsM(book.seed, 1);
      else if (key === "pre_m") text = fmtIlsM(book.pre_money, 0);
      if (text != null && text.indexOf("NaN") === -1) fillEl(el, text);
    }
  }

  function rewriteEscapedModuleClaims(root) {
    var n = String(modules());
    var nodes = (root || document).querySelectorAll("td, input[type='text']");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var isInput = el.tagName === "INPUT";
      var raw = isInput ? el.value : el.textContent;
      if (!raw || raw.indexOf("modules") === -1) continue;
      var next = raw.replace(/\((\d+)\+?\s+modules\)/g, "(" + n + " modules)");
      if (next === raw) continue;
      if (isInput) {
        if (el.value !== next) el.value = next;
      } else {
        fillEl(el, next);
      }
    }
  }

  function apply(root) {
    if (applying) return;
    applying = true;
    try {
      applyModules(root);
      applyBook(root);
      rewriteEscapedModuleClaims(root);
    } finally {
      applying = false;
    }
  }

  function setFacts(payload) {
    if (!payload || typeof payload !== "object") return;
    if (typeof payload.service_modules === "number") {
      facts.service_modules = payload.service_modules;
    }
    if (payload.investor_book) facts.investor_book = payload.investor_book;
    if (payload.source) facts.source = payload.source;
    apply();
    try {
      global.dispatchEvent(new CustomEvent("phins:platform-facts", { detail: {
        service_modules: facts.service_modules,
        investor_book: facts.investor_book,
        source: facts.source
      }}));
    } catch (e) {}
  }

  function load() {
    apply();
    fetch("/api/platform/facts", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(setFacts)
      .catch(function () {});
  }

  global.PhinsPlatformFacts = {
    get service_modules() { return modules(); },
    modules: modules,
    get investor_book() { return facts.investor_book; },
    apply: apply,
    set: setFacts
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }

  if (global.MutationObserver) {
    var timer = null;
    var obs = new MutationObserver(function () {
      if (applying) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(function () { apply(); }, 40);
    });
    function arm() {
      if (!document.documentElement) return;
      obs.observe(document.documentElement, { childList: true, subtree: true });
    }
    if (document.documentElement) arm();
    else document.addEventListener("DOMContentLoaded", arm);
  }
})(window);
