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

    function ensureLetterheadCss() {
        if (!global.document || !global.document.head) return;
        if (global.document.querySelector('link[href="/phins-document.css"]')) return;
        const css = global.document.createElement('link');
        css.rel = 'stylesheet';
        css.href = '/phins-document.css';
        css.setAttribute('data-phins-letterhead-css', '1');
        global.document.head.appendChild(css);
    }

    function letterheadArticle(title, eyebrow) {
        const article = global.document.createElement('article');
        article.className = 'phins-doc';
        const header = global.document.createElement('header');
        header.className = 'phins-doc-banner';
        header.innerHTML = '<div class="phins-doc-brand"><div class="phins-doc-logo">'
            + '<img src="/phins-logo.svg" alt=""></div><div>'
            + '<div class="phins-doc-wordmark">PHINS</div>'
            + '<div class="phins-doc-tagline">Personal Health Insurance &amp; Savings</div>'
            + '</div></div><div class="phins-doc-kicker">'
            + esc(eyebrow || 'PHINS') + '<span>' + esc(title || '') + '</span></div>';
        const gold = global.document.createElement('div');
        gold.className = 'phins-doc-gold';
        const body = global.document.createElement('div');
        body.className = 'phins-doc-body';
        const foot = global.document.createElement('footer');
        foot.className = 'phins-doc-foot';
        foot.textContent = 'PHINS document. The stored record is unchanged.';
        article.appendChild(header);
        article.appendChild(gold);
        article.appendChild(body);
        article.appendChild(foot);
        return { article: article, body: body };
    }

    function wrapElement(node, title, eyebrow) {
        ensureLetterheadCss();
        const built = letterheadArticle(title, eyebrow);
        if (node) built.body.appendChild(node);
        return built.article;
    }

    function adoptPage() {
        const doc = global.document;
        if (!doc || !doc.body) return;
        if (doc.querySelector('.phins-doc-banner')) return;
        if (doc.documentElement.getAttribute('data-phins-letterhead') === 'off') return;
        if (doc.body.getAttribute('data-phins-return') === 'off') return;
        try { if (global.top !== global.self) return; } catch (e) { return; }
        if (doc.body.getAttribute('data-phins-letterhead-mounted') === '1') return;
        doc.body.setAttribute('data-phins-letterhead-mounted', '1');
        ensureLetterheadCss();
        const title = doc.title || 'PHINS document';
        const eyebrow = doc.documentElement.getAttribute('data-phins-eyebrow') || 'PHINS';
        const built = letterheadArticle(title, eyebrow);
        const bar = doc.querySelector('.phins-doc-return');
        Array.prototype.slice.call(doc.body.childNodes).forEach(function (node) {
            if (node === bar) return;
            built.body.appendChild(node);
        });
        doc.body.appendChild(built.article);
    }

    async function openStoredFile(opts) {
        const file = opts && opts.blob;
        if (!file) return null;
        const title = (opts && opts.title) || 'PHINS document';
        const url = URL.createObjectURL(file);
        const html = await render({
            title: title,
            eyebrow: (opts && opts.eyebrow) || 'PHINS',
            subtitle: title,
            body: '<iframe class="phins-file-frame" title="' + esc(title) + '" src="' + url + '"></iframe>',
            footer: 'The file inside this letterhead is the stored record. Its bytes are unchanged.'
        });
        const opened = openWindow(html);
        if (opened) return opened;
        const save = global.document.createElement('a');
        save.href = url;
        save.download = (opts && opts.filename) || 'phins-document.pdf';
        global.document.body.appendChild(save);
        save.click();
        save.remove();
        return null;
    }

    global.PhinsDocument = {
        render: render,
        save: save,
        esc: esc,
        openWindow: openWindow,
        printReport: printReport,
        wrapElement: wrapElement,
        adoptPage: adoptPage,
        openStoredFile: openStoredFile
    };
})(window);
