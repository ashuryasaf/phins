/* PHINS document return bar.
   Every report, file, or document a person can open must include this script
   (or the markup from services/phins_document.py, which inlines it) so the
   page is never a dead end. Chrome only: it does not read or rewrite document
   data. Future generated documents call PhinsDocument.printReport /
   render_phins_document, or load /phins-doc-return.js with a script tag.
   This file is also inlined inside a script element, so it must never
   contain a literal script tag: the HTML parser would close the element
   there and print the rest of this source as page text.
   Set data-phins-return="off" on <body> when the page already has its own
   Go back and Close controls that call phinsDocGoBack / phinsDocClose. */
(function (global) {
    'use strict';

    if (global.__phinsDocReturnInstalled) return;
    global.__phinsDocReturnInstalled = true;

    /* Role homes for the cross-pipeline checkout. Keep in sync with
       PIPELINE_DOCUMENT_HOMES in services/phins_document.py. */
    var PHINS_DOCUMENT_HOMES = {
        admin: '/admin.html',
        manager: '/admin.html',
        underwriter: '/underwriter-dashboard.html',
        claims: '/claims-adjuster-dashboard.html',
        claims_adjuster: '/claims-adjuster-dashboard.html',
        adjuster: '/claims-adjuster-dashboard.html',
        accountant: '/accountant-dashboard.html',
        actuary: '/actuary-dashboard.html',
        supplier: '/supplier-portal.html',
        regulator: '/regulator-dashboard.html',
        customer: '/dashboard.html',
        foundation: '/foundation-dashboard.html',
        community: '/foundation-dashboard.html'
    };

    function framed() {
        try { return global.top !== global.self; } catch (e) { return true; }
    }

    function sameOriginPath(value) {
        if (!value || value.charAt(0) !== '/' || value.charAt(1) === '/' || value.indexOf('\\') !== -1) {
            return '';
        }
        if (value.indexOf('..') !== -1) return '';
        return value;
    }

    function phinsDocReturnTarget() {
        try {
            var q = new URLSearchParams(global.location.search || '');
            var explicit = sameOriginPath(q.get('return') || '');
            if (explicit) return explicit;
        } catch (e) { /* keep going */ }
        if (global.document.referrer) {
            try {
                var ref = new URL(global.document.referrer);
                if (ref.origin === global.location.origin && ref.pathname !== global.location.pathname) {
                    return ref.pathname + ref.search + ref.hash;
                }
            } catch (e2) { /* ignore */ }
        }
        var role = '';
        try {
            var raw = global.localStorage.getItem('session') || global.sessionStorage.getItem('session') || '';
            if (raw) role = String((JSON.parse(raw) || {}).role || '').toLowerCase();
        } catch (e3) { /* ignore */ }
        return PHINS_DOCUMENT_HOMES[role] || '/documents.html';
    }

    function phinsDocGoBack() {
        if (framed()) return;
        try {
            if (global.history.length > 1) {
                global.history.back();
                return;
            }
        } catch (e) { /* fall through */ }
        global.location.href = phinsDocReturnTarget();
    }

    function phinsDocClose() {
        if (framed()) return;
        var target = phinsDocReturnTarget();
        try { global.close(); } catch (e) { /* blocked */ }
        global.setTimeout(function () {
            if (!global.closed) global.location.href = target;
        }, 180);
    }

    function ensureStyle() {
        if (global.document.getElementById('phins-doc-return-style')) return;
        var style = global.document.createElement('style');
        style.id = 'phins-doc-return-style';
        style.textContent = ''
            + '.phins-doc-return{position:sticky;top:0;z-index:80;display:flex;justify-content:space-between;'
            + 'align-items:center;gap:12px;padding:10px 16px;background:#fff;color:#12284c;'
            + 'border-bottom:4px solid #c9a04e;font-family:Inter,"Segoe UI",sans-serif;}'
            + '.phins-doc-return-note{font-family:"Space Grotesk",Inter,"Segoe UI",sans-serif;font-weight:600;'
            + 'letter-spacing:.06em;font-size:12px;color:#0e2f63;}'
            + '.phins-doc-return-actions{display:flex;gap:8px;flex-wrap:wrap;}'
            + '.phins-doc-return button{font:600 13px Inter,"Segoe UI",sans-serif;border-radius:8px;padding:8px 14px;cursor:pointer;}'
            + '.phins-doc-back{background:#fff;color:#0e2f63;border:1px solid #d5deea;}'
            + '.phins-doc-close{background:linear-gradient(135deg,#060d1f 0%,#0e2f63 46%,#123f82 100%);color:#fff;border:0;}'
            + '@media print{.phins-doc-return{display:none !important;}}';
        (global.document.head || global.document.documentElement).appendChild(style);
    }

    function buildBar() {
        var bar = global.document.createElement('nav');
        bar.className = 'phins-doc-return';
        bar.setAttribute('aria-label', 'Leave this document');
        bar.innerHTML = '<span class="phins-doc-return-note">PHINS document</span>'
            + '<span class="phins-doc-return-actions">'
            + '<button type="button" class="phins-doc-back">Go back</button>'
            + '<button type="button" class="phins-doc-close">Close</button>'
            + '</span>';
        return bar;
    }

    function mount() {
        ensureStyle();
        var existing = global.document.querySelector('.phins-doc-return');
        var off = global.document.body && global.document.body.getAttribute('data-phins-return') === 'off';
        if (framed()) {
            if (existing) existing.hidden = true;
            return;
        }
        if (!existing && !off && global.document.body) {
            global.document.body.insertBefore(buildBar(), global.document.body.firstChild);
        }
    }

    global.phinsDocGoBack = phinsDocGoBack;
    global.phinsDocClose = phinsDocClose;
    global.PHINS_DOCUMENT_HOMES = PHINS_DOCUMENT_HOMES;

    global.document.addEventListener('click', function (event) {
        var node = event.target && event.target.closest
            ? event.target.closest('.phins-doc-back, .phins-doc-close')
            : null;
        if (!node || framed()) return;
        event.preventDefault();
        if (node.classList.contains('phins-doc-close')) phinsDocClose();
        else phinsDocGoBack();
    });

    if (global.document.readyState === 'loading') {
        global.document.addEventListener('DOMContentLoaded', mount);
    } else {
        mount();
    }
})(window);
