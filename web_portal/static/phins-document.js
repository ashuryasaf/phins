/* Build and download a self-contained PHINS letterhead document. */
(function (global) {
    'use strict';

    let cssText = '';
    let logoText = '';

    async function assets() {
        if (!cssText || !logoText) {
            const [css, logo] = await Promise.all([
                fetch('/phins-document.css').then((r) => r.text()),
                fetch('/phins-logo.svg').then((r) => r.text()),
            ]);
            cssText = css;
            logoText = logo;
        }
        return { css: cssText, logo: logoText };
    }

    function esc(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    async function render(opts) {
        const pack = await assets();
        const title = esc(opts.title || 'PHINS document');
        const eyebrow = esc(opts.eyebrow || 'PHINS');
        const subtitle = esc(opts.subtitle || '');
        const footer = opts.footer || '';
        return '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            + '<meta name="viewport" content="width=device-width, initial-scale=1">'
            + '<title>' + title + '</title><style>' + pack.css + '</style></head><body>'
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

    global.PhinsDocument = { render: render, save: save, esc: esc };
})(window);
