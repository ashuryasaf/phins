/* Build and download a self-contained PHINS letterhead document.
   Future reports call PhinsDocument.render or PhinsDocument.printReport so
   the file carries the emblem, navy/gold gradient, and a Go back / Close bar.
   The bar is chrome only; opts.body is inserted unchanged. */
(function (global) {
    'use strict';

    let cssText = '';
    let logoText = '';
    let returnJs = '';

    async function assets() {
        if (!cssText || !logoText || !returnJs) {
            const [css, logo, ret] = await Promise.all([
                fetch('/phins-document.css').then((r) => {
                    if (!r.ok) throw new Error('PHINS document style is unavailable');
                    return r.text();
                }),
                fetch('/phins-logo.svg').then((r) => {
                    if (!r.ok) throw new Error('PHINS emblem is unavailable');
                    return r.text();
                }),
                fetch('/phins-doc-return.js').then((r) => {
                    if (!r.ok) throw new Error('PHINS document return bar is unavailable');
                    return r.text();
                }),
            ]);
            cssText = css;
            logoText = logo;
            returnJs = ret;
        }
        return { css: cssText, logo: logoText, returnJs: returnJs };
    }

    function esc(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function returnMarkup(script) {
        return '<nav class="phins-doc-return" aria-label="Leave this document">'
            + '<span class="phins-doc-return-note">PHINS document</span>'
            + '<span class="phins-doc-return-actions">'
            + '<button type="button" class="phins-doc-back">Go back</button>'
            + '<button type="button" class="phins-doc-close">Close</button>'
            + '</span></nav><script>' + script + '<\/script>';
    }

    async function render(opts) {
        const pack = await assets();
        const title = esc(opts.title || 'PHINS document');
        const eyebrow = esc(opts.eyebrow || 'PHINS');
        const subtitle = esc(opts.subtitle || '');
        const footer = opts.footer || '';
        return '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            + '<meta name="viewport" content="width=device-width, initial-scale=1">'
            + '<title>' + title + '</title>'
            + '<link rel="preconnect" href="https://fonts.googleapis.com">'
            + '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">'
            + '<style>' + pack.css + '</style></head><body>'
            + returnMarkup(pack.returnJs)
            + '<article class="phins-doc"><header class="phins-doc-banner">'
            + '<div class="phins-doc-brand"><div class="phins-doc-logo">' + pack.logo + '</div>'
            + '<div><div class="phins-doc-wordmark">PHINS</div>'
            + '<div class="phins-doc-tagline">Personal Health Insurance &amp; Savings</div></div></div>'
            + '<div class="phins-doc-kicker">' + eyebrow + '<span>' + subtitle + '</span></div>'
            + '</header><div class="phins-doc-gold"></div><div class="phins-doc-body">'
            + (opts.body || '')
            + '</div><footer class="phins-doc-foot">' + footer + '</footer></article></body></html>';
    }

    function save(filename, html) {
        const blob = new Blob([html || ''], { type: 'text/html' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    }

    function openWindow(html) {
        const printWindow = window.open('', '_blank');
        if (!printWindow) return null;
        printWindow.document.open();
        printWindow.document.write(html || '');
        printWindow.document.close();
        return printWindow;
    }

    async function printReport(opts) {
        const html = await render(opts || {});
        const printWindow = openWindow(html);
        if (!printWindow) return null;
        setTimeout(function () {
            try { printWindow.focus(); printWindow.print(); } catch (e) { /* popup still holds the document */ }
        }, 400);
        return printWindow;
    }

    global.PhinsDocument = {
        render: render,
        save: save,
        esc: esc,
        openWindow: openWindow,
        printReport: printReport
    };
})(window);
