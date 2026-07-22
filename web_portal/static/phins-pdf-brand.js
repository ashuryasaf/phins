/* ============================================================================
 * PHINS — shared jsPDF branding helper
 * ----------------------------------------------------------------------------
 * window.PhinsPdfBrand gives every client-generated (jsPDF) download the same
 * first-level document identity as the committed investor PDFs produced by
 * scripts/generate_investor_pdfs.py:
 *   • shield-logo letterhead with the PHINS wordmark + tagline
 *   • gold / navy double rule under the letterhead
 *   • slim running header (emblem + document title) on continuation pages
 *   • branded footer on every page (gold hairline, emblem, note, page x of y)
 *
 * Data-integrity contract: this module draws chrome ONLY — headers, rules and
 * footers. It never reads, injects or transforms document data, so the figures
 * rendered by each generator are byte-for-byte what that generator computed.
 * The logo raster is fetched once from /phins-logo.png (the committed raster of
 * /phins-logo.svg); when unavailable the letterhead falls back to a text-only
 * wordmark so downloads never break on the asset.
 * ==========================================================================*/
(function () {
  'use strict';

  // Brand constants — keep in sync with scripts/generate_investor_pdfs.py
  var NAVY = [14, 47, 99];      // #0e2f63 shield navy from phins-logo.svg
  var GOLD = [201, 160, 78];    // #c9a04e gold rim from phins-logo.svg
  var BLUE = [13, 71, 161];     // #0d47a1 PHINS primary blue
  var GREY = [91, 107, 130];    // #5b6b82 letterhead grey
  var BRAND_NAME = 'PHINS';
  var BRAND_TAGLINE = 'Personal Health Insurance & Savings · AI-Operated Insurance Platform';
  var LOGO_URL = '/phins-logo.png';

  var logoDataUrl = null;
  var logoPromise = null;

  function preload() {
    if (logoPromise) return logoPromise;
    logoPromise = fetch(LOGO_URL)
      .then(function (r) { if (!r.ok) throw new Error('logo unavailable'); return r.blob(); })
      .then(function (blob) {
        return new Promise(function (resolve) {
          var reader = new FileReader();
          reader.onload = function () {
            // The static server may label the raster application/octet-stream;
            // jsPDF needs a real image mime to decode the data URL, and the
            // committed asset is a PNG, so normalize the prefix.
            logoDataUrl = String(reader.result || '')
              .replace(/^data:[^;]*;base64,/, 'data:image/png;base64,');
            resolve(logoDataUrl);
          };
          reader.onerror = function () { resolve(null); };
          reader.readAsDataURL(blob);
        });
      })
      .catch(function () { return null; });
    return logoPromise;
  }

  function truncateToWidth(doc, text, maxWidth) {
    text = String(text || '');
    if (doc.getTextWidth(text) <= maxWidth) return text;
    var ell = '…';
    while (text && doc.getTextWidth(text + ell) > maxWidth) {
      text = text.slice(0, -1);
    }
    return text ? text + ell : ell;
  }

  /**
   * Draw the branded letterhead at the top of the current page.
   * opts: { title, subtitle, meta (array of small lines), margin }
   * Returns the y coordinate where document content should start.
   */
  function letterhead(doc, opts) {
    opts = opts || {};
    var m = opts.margin || 40;
    var pw = doc.internal.pageSize.getWidth();
    var tw = pw - m * 2;
    var y = m - 6;

    // shield emblem + wordmark + tagline
    var textX = m;
    if (logoDataUrl) {
      try {
        doc.addImage(logoDataUrl, 'PNG', m, y - 8, 42, 42);
        textX = m + 52;
      } catch (e) { textX = m; }
    }
    doc.setFont(undefined, 'bold');
    doc.setFontSize(21);
    doc.setTextColor(NAVY[0], NAVY[1], NAVY[2]);
    doc.text(BRAND_NAME, textX, y + 12);
    doc.setFont(undefined, 'normal');
    doc.setFontSize(6.8);
    doc.setTextColor(GREY[0], GREY[1], GREY[2]);
    doc.text(BRAND_TAGLINE, textX, y + 22);
    y += 42;

    // gold + navy double rule (the first-level document signature)
    doc.setDrawColor(GOLD[0], GOLD[1], GOLD[2]);
    doc.setLineWidth(2.2);
    doc.line(m, y, pw - m, y);
    doc.setDrawColor(NAVY[0], NAVY[1], NAVY[2]);
    doc.setLineWidth(0.8);
    doc.line(m, y + 3.4, pw - m, y + 3.4);
    y += 20;

    // document title / subtitle / meta lines
    if (opts.title) {
      doc.setFont(undefined, 'bold');
      doc.setFontSize(17);
      doc.setTextColor(NAVY[0], NAVY[1], NAVY[2]);
      var titleLines = doc.splitTextToSize(String(opts.title), tw);
      doc.text(titleLines, m, y);
      y += titleLines.length * 19;
    }
    if (opts.subtitle) {
      doc.setFont(undefined, 'normal');
      doc.setFontSize(9.5);
      doc.setTextColor(BLUE[0], BLUE[1], BLUE[2]);
      var subLines = doc.splitTextToSize(String(opts.subtitle), tw);
      doc.text(subLines, m, y);
      y += subLines.length * 12 + 2;
    }
    (opts.meta || []).forEach(function (line) {
      doc.setFont(undefined, 'normal');
      doc.setFontSize(7.6);
      doc.setTextColor(GREY[0], GREY[1], GREY[2]);
      var metaLines = doc.splitTextToSize(String(line), tw);
      doc.text(metaLines, m, y);
      y += metaLines.length * 10;
    });

    doc.setTextColor(0, 0, 0);
    doc.setFont(undefined, 'normal');
    return y + 8;
  }

  /**
   * Decorate every page after content generation:
   * branded footer on all pages + slim running header on pages >= 2.
   * opts: { title, note, margin }
   */
  function finalize(doc, opts) {
    opts = opts || {};
    var m = opts.margin || 40;
    var pw = doc.internal.pageSize.getWidth();
    var ph = doc.internal.pageSize.getHeight();
    var note = opts.note || (BRAND_NAME + ' — Confidential investor document');
    var pageCount = doc.getNumberOfPages();

    for (var p = 1; p <= pageCount; p++) {
      doc.setPage(p);

      // running header (continuation pages only)
      if (p > 1 && opts.title) {
        var hy = 24;
        doc.setFont(undefined, 'bold');
        doc.setFontSize(7.5);
        doc.setTextColor(NAVY[0], NAVY[1], NAVY[2]);
        var titleX = m;
        if (logoDataUrl) {
          try {
            doc.addImage(logoDataUrl, 'PNG', m, hy - 10, 13, 13);
            titleX = m + 17;
          } catch (e) { titleX = m; }
        }
        doc.text(truncateToWidth(doc, opts.title, pw - m - titleX - 60), titleX, hy);
        doc.setDrawColor(GOLD[0], GOLD[1], GOLD[2]);
        doc.setLineWidth(0.9);
        doc.line(m, hy + 5, pw - m, hy + 5);
      }

      // footer: gold hairline · emblem · note · page number
      doc.setDrawColor(GOLD[0], GOLD[1], GOLD[2]);
      doc.setLineWidth(0.9);
      doc.line(m, ph - 30, pw - m, ph - 30);
      doc.setFont(undefined, 'normal');
      doc.setFontSize(6.8);
      doc.setTextColor(GREY[0], GREY[1], GREY[2]);
      var noteX = m;
      if (logoDataUrl) {
        try {
          doc.addImage(logoDataUrl, 'PNG', m, ph - 26, 11, 11);
          noteX = m + 15;
        } catch (e) { noteX = m; }
      }
      doc.text(truncateToWidth(doc, note, pw - noteX - m - 66), noteX, ph - 18);
      doc.text('Page ' + p + ' of ' + pageCount, pw - m, ph - 18, { align: 'right' });
    }

    doc.setTextColor(0, 0, 0);
    doc.setFont(undefined, 'normal');
  }

  window.PhinsPdfBrand = {
    NAVY: NAVY,
    GOLD: GOLD,
    BLUE: BLUE,
    GREY: GREY,
    BRAND_NAME: BRAND_NAME,
    BRAND_TAGLINE: BRAND_TAGLINE,
    preload: preload,
    letterhead: letterhead,
    finalize: finalize
  };

  // Start fetching the logo immediately so it is ready by first download.
  preload();
})();
