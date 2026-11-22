/* PHINS brand mark: "PHINS©" with "All rights reserved" set underneath.
   The reserved line is tracked so it spans exactly the width of the
   wordmark, in letters smaller than the wordmark, wherever the logo appears
   (dashboard headers, login, documents, decks). The host element keeps its
   own classes and styles; only its leading "PHINS" text is replaced, so a
   page's gradient, colour and responsive rules still apply. Add
   data-phins-mark="off" to an element to leave its subtree alone.
   Never put a literal script end tag in this file: it is inlined into
   generated documents. */
(function () {
    'use strict';

    if (typeof window === 'undefined' || typeof document === 'undefined') return;
    if (window.__phinsBrandMark) return;

    var STYLE_ID = 'phins-brand-mark-style';
    var RIGHTS = 'All rights reserved';
    var HOSTS = [
        '.phins-logo-text', '.logo-text', '.brand-wordmark', '.lh-name',
        '.phins-doc-wordmark', '.deck-word', '.cover-logo-text', '.bc-brand',
        '.splash-text', '.bp-wordmark', '.wordmark', '.sol-theater-wordmark',
        '.auth-wordmark', '.ld-logo-text', '.brand', '.cyber-logo > span',
        '.cover-wordmark', '.lp-wordmark', '[data-phins-mark-host]'
    ].join(',');
    var LEADING = /^(\s*)PHINS(?![A-Za-z0-9_\u00A9])/;
    var TRACKING_EM = 0.08;
    var MIN_TRACKING_EM = -0.04;
    var MAX_SIZE_RATIO = 0.34;

    var CSS = ''
        + '.phins-mark{display:inline-grid;grid-template-columns:max-content;'
        + 'row-gap:0.12em;line-height:1;direction:ltr;unicode-bidi:isolate;'
        + 'text-align:left;vertical-align:baseline;white-space:nowrap;}'
        + '.phins-mark-word{display:block;white-space:nowrap;}'
        + '.phins-mark-c{font-size:0.42em;line-height:0;letter-spacing:0;'
        + 'vertical-align:0.92em;margin-left:0.06em;font-weight:600;'
        + 'font-family:Inter,"Segoe UI",Arial,sans-serif;}'
        + '.phins-mark-rights{display:block;width:0;min-width:100%;overflow:visible;'
        + 'white-space:nowrap;font-family:Inter,"Segoe UI",Arial,sans-serif;'
        + 'font-weight:600;font-style:normal;text-transform:uppercase;line-height:1;'
        + 'font-size:0.26em;letter-spacing:0.04em;text-align:justify;'
        + 'text-align-last:justify;text-shadow:none;}'
        + '.phins-mark-rights.is-fitted{text-align:left;text-align-last:auto;}'
        + '.phins-mark-measure{position:absolute;visibility:hidden;left:-9999px;top:0;'
        + 'width:auto;min-width:0;font-size:100px;letter-spacing:0;}';

    function ensureStyle() {
        if (document.getElementById(STYLE_ID)) return;
        var style = document.createElement('style');
        style.id = STYLE_ID;
        style.textContent = CSS;
        (document.head || document.documentElement).appendChild(style);
    }

    function skipped(el) {
        return !!(el.closest && el.closest(
            '[data-phins-mark="off"],[contenteditable="true"],textarea,input,select,svg,script,style,title'
        ));
    }

    function buildMark() {
        var mark = document.createElement('span');
        mark.className = 'phins-mark';
        mark.setAttribute('data-phins-mark', 'on');
        mark.setAttribute('aria-label', 'PHINS \u00A9 ' + RIGHTS);
        mark.setAttribute('role', 'img');
        var word = document.createElement('span');
        word.className = 'phins-mark-word';
        word.appendChild(document.createTextNode('PHINS'));
        var c = document.createElement('span');
        c.className = 'phins-mark-c';
        c.setAttribute('aria-hidden', 'true');
        c.textContent = '\u00A9';
        word.appendChild(c);
        var rights = document.createElement('span');
        rights.className = 'phins-mark-rights';
        rights.setAttribute('aria-hidden', 'true');
        rights.textContent = RIGHTS;
        mark.appendChild(word);
        mark.appendChild(rights);
        return mark;
    }

    function decorate(host) {
        if (!host || host.nodeType !== 1 || skipped(host)) return null;
        if (host.querySelector('.phins-mark')) return null;
        for (var node = host.firstChild; node; node = node.nextSibling) {
            if (node.nodeType !== 3) continue;
            var text = node.nodeValue || '';
            if (!text.trim()) continue;
            var m = LEADING.exec(text);
            if (!m) return null;
            var mark = buildMark();
            var before = m[1];
            var after = text.slice(m[0].length);
            var parent = node.parentNode;
            if (before) parent.insertBefore(document.createTextNode(before), node);
            parent.insertBefore(mark, node);
            if (after) {
                parent.insertBefore(document.createTextNode(after), node);
                host.style.whiteSpace = 'nowrap';
            }
            parent.removeChild(node);
            return mark;
        }
        return null;
    }

    function px(value) {
        var n = parseFloat(value);
        return isFinite(n) ? n : 0;
    }

    function naturalWidthPer100(rights) {
        var probe = rights.cloneNode(true);
        probe.className = 'phins-mark-rights phins-mark-measure';
        probe.removeAttribute('style');
        rights.parentNode.appendChild(probe);
        var w = probe.getBoundingClientRect().width;
        probe.parentNode.removeChild(probe);
        return w / 100;
    }

    function fit(mark) {
        var word = mark.querySelector('.phins-mark-word');
        var c = mark.querySelector('.phins-mark-c');
        var rights = mark.querySelector('.phins-mark-rights');
        if (!word || !rights) return;
        var wordStyle = window.getComputedStyle(word);
        var hostSize = px(wordStyle.fontSize);
        var hostTracking = px(wordStyle.letterSpacing);
        if (c && hostTracking > 0) {
            c.style.marginLeft = (0.06 * hostSize * 0.42 - hostTracking * 0.6).toFixed(2) + 'px';
        }
        var target = word.getBoundingClientRect().width;
        if (!(target > 0) || !(hostSize > 0)) return;
        var k = naturalWidthPer100(rights);
        if (!(k > 0)) return;
        var gaps = RIGHTS.length - 1;
        var size = target / (k + TRACKING_EM * gaps);
        size = Math.min(size, hostSize * MAX_SIZE_RATIO);
        var tracking = (target - k * size) / gaps;
        if (tracking < MIN_TRACKING_EM * size) {
            size = target / (k + MIN_TRACKING_EM * gaps);
            tracking = MIN_TRACKING_EM * size;
        }
        rights.style.fontSize = size.toFixed(3) + 'px';
        rights.style.letterSpacing = tracking.toFixed(3) + 'px';
        rights.style.marginRight = (-tracking).toFixed(3) + 'px';
        rights.classList.add('is-fitted');
        mark.style.rowGap = Math.max(1, hostSize * 0.1).toFixed(2) + 'px';
    }

    var resizeObserver = null;
    if (typeof window.ResizeObserver === 'function') {
        resizeObserver = new window.ResizeObserver(function (entries) {
            for (var i = 0; i < entries.length; i++) {
                var mark = entries[i].target.closest && entries[i].target.closest('.phins-mark');
                if (mark) fit(mark);
            }
        });
    }

    function track(mark) {
        fit(mark);
        if (resizeObserver) {
            var word = mark.querySelector('.phins-mark-word');
            if (word) resizeObserver.observe(word);
        }
    }

    function scan(root) {
        if (!root || !root.querySelectorAll) return;
        var hosts = [];
        if (root.matches && root.matches(HOSTS)) hosts.push(root);
        var found = root.querySelectorAll(HOSTS);
        for (var i = 0; i < found.length; i++) hosts.push(found[i]);
        for (var j = 0; j < hosts.length; j++) {
            var mark = decorate(hosts[j]);
            if (mark) track(mark);
        }
    }

    function refitAll() {
        var marks = document.querySelectorAll('.phins-mark');
        for (var i = 0; i < marks.length; i++) fit(marks[i]);
    }

    var pending = [];
    var scheduled = false;
    function schedule(node) {
        pending.push(node);
        if (scheduled) return;
        scheduled = true;
        var run = function () {
            scheduled = false;
            var batch = pending;
            pending = [];
            for (var i = 0; i < batch.length; i++) {
                if (batch[i].isConnected !== false) scan(batch[i]);
            }
        };
        if (window.requestAnimationFrame) window.requestAnimationFrame(run);
        else setTimeout(run, 16);
    }

    function start() {
        ensureStyle();
        scan(document.body || document.documentElement);
        if (document.fonts && document.fonts.ready) {
            document.fonts.ready.then(refitAll).catch(function () {});
        }
        window.addEventListener('load', refitAll);
        window.addEventListener('beforeprint', refitAll);
        if (typeof window.MutationObserver === 'function' && document.body) {
            new window.MutationObserver(function (mutations) {
                for (var i = 0; i < mutations.length; i++) {
                    var mu = mutations[i];
                    if (mu.type === 'characterData') {
                        if (mu.target.parentNode) schedule(mu.target.parentNode);
                        continue;
                    }
                    for (var j = 0; j < mu.addedNodes.length; j++) {
                        var n = mu.addedNodes[j];
                        if (n.nodeType === 1) schedule(n);
                        else if (n.nodeType === 3 && n.parentNode) schedule(n.parentNode);
                    }
                }
            }).observe(document.body, { childList: true, subtree: true, characterData: true });
        }
    }

    window.__phinsBrandMark = { scan: scan, refit: refitAll, text: RIGHTS };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start, { once: true });
    } else {
        start();
    }
})();
