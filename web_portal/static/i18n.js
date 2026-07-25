/**
 * PHINS i18n engine
 * =================
 * Lightweight client-side localization used by the customer journey pages.
 *
 * How it works:
 *  - The active language is stored in localStorage under "phins_language".
 *  - Dictionaries live at /locales/{lang}.json with the shape:
 *      { "dir": "rtl", "name": "עברית", "keys": {...}, "strings": {...} }
 *    "strings" maps exact English source text -> translated text and is applied
 *    to text nodes and safe attributes. "keys" backs data-i18n="key" lookups.
 *  - A MutationObserver re-translates content rendered later by page scripts,
 *    so dynamically injected rows/messages are localized too.
 *  - When the dictionary declares dir=rtl the whole document flips to RTL
 *    (styling handled by /i18n-rtl.css).
 *
 * Usage: include <script src="/i18n.js"></script> in <head> (not deferred, so
 * the dir attribute applies before first paint). Optional page hooks:
 *  - <element data-i18n="key">           translate content by key
 *  - <element data-no-i18n>              never translate this subtree
 *  - window.PHINS_I18N_NO_TOGGLE = true  suppress the floating toggle
 *  - PhinsI18n.setLanguage('he'|'en')    switch programmatically
 */
(function () {
  'use strict';

  var LANG_STORAGE_KEY = 'phins_language';
  var DEFAULT_LANG = 'en';
  var TRANSLATED_LANGS = { he: 'עברית' };
  var ATTRS = ['placeholder', 'title', 'alt', 'aria-label'];
  var SKIP_TAGS = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, CODE: 1, PRE: 1, TEXTAREA: 1 };

  var dict = null;
  var observer = null;

  function safeGet(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }
  function safeSet(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) { /* private mode */ }
  }

  function currentLang() {
    var l = safeGet(LANG_STORAGE_KEY) || DEFAULT_LANG;
    return TRANSLATED_LANGS[l] ? l : DEFAULT_LANG;
  }

  function lookup(text) {
    if (!dict || !text) return null;
    var exact = dict.strings[text];
    if (exact) return exact;
    // Tolerate a leading emoji/symbol prefix (e.g. "📊 Reports")
    var m = text.match(/^([^A-Za-z]*)([A-Za-z].*?)([^A-Za-z0-9%$)?!.']*)$/);
    if (m && m[2]) {
      var core = dict.strings[m[2]];
      if (core) return (m[1] || '') + core + (m[3] || '');
    }
    return null;
  }

  function translateTextNode(node) {
    var value = node.nodeValue;
    if (!value || !/[A-Za-z]/.test(value)) return;
    var trimmed = value.replace(/\s+/g, ' ').trim();
    var translated = lookup(trimmed);
    if (translated && translated !== trimmed) {
      var lead = value.match(/^\s*/)[0];
      var tail = value.match(/\s*$/)[0];
      node.nodeValue = lead + translated + tail;
    }
  }

  function isSkipped(el) {
    for (var n = el; n && n.nodeType === 1; n = n.parentElement) {
      if (SKIP_TAGS[n.tagName] || n.hasAttribute('data-no-i18n') || n.getAttribute('translate') === 'no') return true;
    }
    return false;
  }

  function translateElementAttrs(el) {
    if (isSkipped(el)) return;
    for (var i = 0; i < ATTRS.length; i++) {
      var attr = ATTRS[i];
      var v = el.getAttribute && el.getAttribute(attr);
      if (v) {
        var tr = lookup(v.trim());
        if (tr) el.setAttribute(attr, tr);
      }
    }
    // Buttons/submits keep their submitted value untouched except display-only inputs
    if ((el.tagName === 'INPUT') && (el.type === 'button' || el.type === 'submit')) {
      var bv = el.getAttribute('value');
      if (bv) {
        var btr = lookup(bv.trim());
        if (btr) el.setAttribute('value', btr);
      }
    }
    var key = el.getAttribute && el.getAttribute('data-i18n');
    if (key && dict.keys && dict.keys[key]) el.textContent = dict.keys[key];
  }

  function translateTree(root) {
    if (!dict) return;
    if (root.nodeType === 3) {
      if (!isSkipped(root.parentElement)) translateTextNode(root);
      return;
    }
    if (root.nodeType !== 1 && root.nodeType !== 9 && root.nodeType !== 11) return;
    if (root.nodeType === 1) {
      if (isSkipped(root)) return;
      translateElementAttrs(root);
    }
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
      acceptNode: function (n) {
        if (n.nodeType === 1 && (SKIP_TAGS[n.tagName] || n.hasAttribute('data-no-i18n') || n.getAttribute('translate') === 'no')) {
          return NodeFilter.FILTER_REJECT; // skip the whole subtree
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    var node;
    while ((node = walker.nextNode())) {
      if (node.nodeType === 1) translateElementAttrs(node);
      else if (node.nodeType === 3) translateTextNode(node);
    }
  }

  function translateTitle() {
    if (!dict) return;
    var tr = lookup(document.title.trim());
    if (tr) document.title = tr;
  }

  function startObserver() {
    if (observer || !dict) return;
    observer = new MutationObserver(function (mutations) {
      for (var i = 0; i < mutations.length; i++) {
        var m = mutations[i];
        if (m.type === 'characterData') {
          if (m.target.parentElement && !isSkipped(m.target.parentElement)) translateTextNode(m.target);
        } else if (m.type === 'childList') {
          for (var j = 0; j < m.addedNodes.length; j++) translateTree(m.addedNodes[j]);
        }
      }
    });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  }

  function applyDirection(lang) {
    var rtl = dict && dict.dir === 'rtl';
    document.documentElement.setAttribute('lang', lang);
    document.documentElement.setAttribute('dir', rtl ? 'rtl' : 'ltr');
    if (rtl) document.documentElement.classList.add('phins-rtl');
    else document.documentElement.classList.remove('phins-rtl');
  }

  function injectToggle(lang) {
    if (window.PHINS_I18N_NO_TOGGLE) return;
    if (document.getElementById('language-selector')) return; // page has its own selector
    if (document.getElementById('phins-lang-toggle')) return;
    var wrap = document.createElement('div');
    wrap.id = 'phins-lang-toggle';
    wrap.setAttribute('data-no-i18n', '');
    wrap.setAttribute('role', 'group');
    wrap.setAttribute('aria-label', 'Language / שפה');
    var langs = [['en', 'EN'], ['he', 'עברית']];
    for (var i = 0; i < langs.length; i++) {
      (function (code, label) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.textContent = label;
        btn.className = 'phins-lang-btn' + (lang === code ? ' active' : '');
        btn.addEventListener('click', function () { window.PhinsI18n.setLanguage(code); });
        wrap.appendChild(btn);
      })(langs[i][0], langs[i][1]);
    }
    document.body.appendChild(wrap);
  }

  function boot() {
    var lang = currentLang();
    if (lang === DEFAULT_LANG) {
      onReady(function () { injectToggle(lang); });
      return;
    }
    // Fetch dictionary early; flip direction as soon as it arrives.
    fetch('/locales/' + lang + '.json', { cache: 'default' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d) return;
        dict = d;
        dict.strings = dict.strings || {};
        dict.keys = dict.keys || {};
        applyDirection(lang);
        onReady(function () {
          translateTitle();
          translateTree(document.body);
          startObserver();
          injectToggle(lang);
          document.dispatchEvent(new CustomEvent('phins:i18n-ready', { detail: { lang: lang } }));
        });
      })
      .catch(function () { /* stay in English */ });
  }

  function onReady(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  window.PhinsI18n = {
    get lang() { return currentLang(); },
    t: function (key) {
      if (!dict) return key;
      return (dict.keys && dict.keys[key]) || lookup(key) || key;
    },
    setLanguage: function (lang) {
      safeSet(LANG_STORAGE_KEY, TRANSLATED_LANGS[lang] ? lang : DEFAULT_LANG);
      // Reload so the whole page (including scripts that cached strings)
      // renders consistently in the selected language.
      window.location.reload();
    },
    translate: function (root) { translateTree(root || document.body); }
  };

  boot();
})();
