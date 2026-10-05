/* Routes a new-tab open of a same-origin PDF or Markdown file through
   /document-viewer.html so the tab has Go back and Close. Download links
   (the download attribute) are left alone. Chrome only: the file bytes
   are unchanged. */
(function (global) {
    'use strict';

    if (global.__phinsDocOpenInstalled) return;
    global.__phinsDocOpenInstalled = true;

    function sameOriginPath(href) {
        if (!href || href.charAt(0) !== '/' || href.charAt(1) === '/' || href.indexOf('\\') !== -1) {
            return '';
        }
        if (href.indexOf('..') !== -1) return '';
        return href;
    }

    global.document.addEventListener('click', function (event) {
        if (event.defaultPrevented || event.button !== 0) return;
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        var node = event.target && event.target.closest ? event.target.closest('a[href]') : null;
        if (!node || node.hasAttribute('download')) return;
        if ((node.getAttribute('target') || '').toLowerCase() !== '_blank') return;
        var href = sameOriginPath(node.getAttribute('href') || '');
        if (!href) return;
        var path = href.split('#')[0].split('?')[0].toLowerCase();
        if (path.indexOf('/document-viewer.html') !== -1) return;
        if (!/\.(pdf|md)$/.test(path)) return;
        event.preventDefault();
        var title = (node.getAttribute('data-title') || node.textContent || 'PHINS document')
            .replace(/\s+/g, ' ').trim().slice(0, 140) || 'PHINS document';
        var url = '/document-viewer.html?src=' + encodeURIComponent(href)
            + '&title=' + encodeURIComponent(title);
        var opened = global.open(url, '_blank', 'noopener');
        if (!opened) global.location.href = url;
    }, true);
})(window);
