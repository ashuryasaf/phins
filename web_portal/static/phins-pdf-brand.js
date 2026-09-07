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
  var BRAND_TAGLINE_HE = 'פלטפורמת ביטוח מופעלת-AI · ביטוח בריאות אישי וחיסכון';
  var LOGO_URL = '/phins-logo.png';
  var FONT_REGULAR_URL = '/fonts/DejaVuSans.ttf';
  var FONT_BOLD_URL = '/fonts/DejaVuSans-Bold.ttf';
  var DOCUMENT_FONT = 'PhinsDejaVu';
  // Baseline where continuation-page body content must start so it clears the
  // running header drawn by finalize() (emblem + title at y≈24, gold rule at
  // y≈29). Generators reset `y` to this on addPage() instead of the top margin.
  var CONTINUATION_TOP = 46;

  var logoDataUrl = null;
  var logoPromise = null;
  var fontCache = {};
  var fontPromise = null;

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
      .catch(function () { return null; })
      .then(function (result) {
        // Don't cache a failed attempt: clearing logoPromise lets a later
        // preload() retry once /phins-logo.png becomes available in the same
        // page session, instead of pinning the text-only fallback forever.
        if (!result) logoPromise = null;
        return result;
      });
    return logoPromise;
  }

  var HE_RE = /[\u0590-\u05FF]/;
  var MIRROR = {
    '(': ')', ')': '(', '[': ']', ']': '[', '{': '}', '}': '{',
    '<': '>', '>': '<', '«': '»', '»': '«'
  };

  function bidiType(ch) {
    var c = ch.charCodeAt(0);
    if (c >= 0x0590 && c <= 0x05FF) return 'R';
    if ((c >= 0x41 && c <= 0x5A) || (c >= 0x61 && c <= 0x7A)) return 'L';
    if (c >= 0x30 && c <= 0x39) return 'EN';
    if (ch === '+' || ch === '-') return 'ES';
    if (ch === '%' || ch === '$' || ch === '#' || ch === '₪' || ch === '¢' || ch === '€' || ch === '£') return 'ET';
    if (ch === ',' || ch === '.' || ch === ':' || ch === '/') return 'CS';
    if (ch === ' ' || ch === '\t' || ch === '\n' || ch === '\r' || c === 0x00A0) return 'WS';
    return 'ON';
  }

  /**
   * Unicode Bidirectional Algorithm (implicit Hebrew + Latin/numbers).
   * jsPDF paints glyphs left-to-right, so RTL copy is converted to visual
   * order after wrapping. Latin tokens (MGA, TAM, AI, PHINS) stay LTR.
   *
   * jsPDF 2.x also runs its own bidi in postProcessText. That second pass
   * is what flipped MGA→AGM / TAM→MAT and spelled the footer backwards.
   * disableJsPdfAutoBidi() strips that pass so this conversion runs once.
   */
  function toVisual(text, rtl) {
    text = String(text == null ? '' : text);
    if (!rtl || !HE_RE.test(text)) return text;
    var chars = Array.from(text);
    var n = chars.length;
    var types = chars.map(bidiType);
    var i;
    var prevStrong = 'R';
    for (i = 0; i < n; i++) {
      if (types[i] === 'ES' || types[i] === 'CS') {
        var prev = i > 0 ? types[i - 1] : '';
        var next = i + 1 < n ? types[i + 1] : '';
        if (prev === 'EN' && next === 'EN') types[i] = 'EN';
      }
    }
    for (i = 0; i < n; i++) {
      if (types[i] === 'ET') {
        var j = i;
        while (j > 0 && types[j - 1] === 'ET') j--;
        var k = i;
        while (k + 1 < n && types[k + 1] === 'ET') k++;
        if ((j > 0 && types[j - 1] === 'EN') || (k + 1 < n && types[k + 1] === 'EN')) {
          for (var t = j; t <= k; t++) types[t] = 'EN';
        }
      }
    }
    for (i = 0; i < n; i++) {
      if (types[i] === 'ES' || types[i] === 'ET' || types[i] === 'CS') types[i] = 'ON';
    }
    prevStrong = 'R';
    for (i = 0; i < n; i++) {
      if (types[i] === 'L' || types[i] === 'R') prevStrong = types[i];
      else if (types[i] === 'EN' && prevStrong === 'L') types[i] = 'L';
    }
    function isNeutral(tp) { return tp === 'WS' || tp === 'ON'; }
    function isStrong(tp) { return tp === 'L' || tp === 'R' || tp === 'EN'; }
    i = 0;
    while (i < n) {
      if (!isNeutral(types[i])) { i++; continue; }
      var start = i;
      while (i < n && isNeutral(types[i])) i++;
      var lead = 'R';
      for (var a = start - 1; a >= 0; a--) {
        if (isStrong(types[a])) { lead = types[a] === 'EN' ? 'L' : types[a]; break; }
      }
      var trail = 'R';
      for (var b = i; b < n; b++) {
        if (isStrong(types[b])) { trail = types[b] === 'EN' ? 'L' : types[b]; break; }
      }
      var resolved = (lead === trail) ? lead : 'R';
      for (var c = start; c < i; c++) types[c] = resolved;
    }
    var levels = types.map(function (tp) {
      if (tp === 'L' || tp === 'EN') return 2;
      return 1;
    });
    function reverseRange(lo, hi) {
      while (lo < hi) {
        var tc = chars[lo];
        chars[lo] = chars[hi];
        chars[hi] = tc;
        var tl = levels[lo];
        levels[lo] = levels[hi];
        levels[hi] = tl;
        lo++;
        hi--;
      }
    }
    var maxLevel = 2;
    for (var lvl = maxLevel; lvl >= 1; lvl--) {
      i = 0;
      while (i < n) {
        if (levels[i] < lvl) { i++; continue; }
        var from = i;
        while (i < n && levels[i] >= lvl) i++;
        reverseRange(from, i - 1);
      }
    }
    for (i = 0; i < n; i++) {
      if (levels[i] % 2 === 1 && MIRROR[chars[i]]) chars[i] = MIRROR[chars[i]];
    }
    return chars.join('');
  }

  /**
   * jsPDF 2.x always bidis in the postProcessText plugin. Undo that pass so
   * our visual-order Hebrew is painted as-is (MGA/TAM stay MGA/TAM).
   */
  function disableJsPdfAutoBidi(doc) {
    var events = doc && doc.internal && doc.internal.events;
    if (!events || typeof events.publish !== 'function' || events.__phinsBidiOff) {
      return doc;
    }
    events.__phinsBidiOff = true;
    var origPublish = events.publish.bind(events);
    events.publish = function (topic, payload) {
      if (topic === 'postProcessText' && payload && payload.text != null) {
        var original = payload.text;
        origPublish(topic, payload);
        payload.text = original;
        return;
      }
      return origPublish(topic, payload);
    };
    return doc;
  }

  function installRtlPainter(doc) {
    if (!doc || typeof doc.text !== 'function') return doc;
    disableJsPdfAutoBidi(doc);
    return doc;
  }

  function wrapLogical(doc, text, maxWidth) {
    text = String(text || '');
    if (!text) return [''];
    if (doc.getTextWidth(text) <= maxWidth) return [text];
    var tokens = text.split(/(\s+)/);
    var lines = [];
    var current = '';
    function flush() {
      if (current) {
        lines.push(current.replace(/\s+$/g, ''));
        current = '';
      }
    }
    function pushHard(chunk) {
      while (chunk && doc.getTextWidth(chunk) > maxWidth) {
        var cut = chunk.length;
        while (cut > 1 && doc.getTextWidth(chunk.slice(0, cut)) > maxWidth) cut--;
        lines.push(chunk.slice(0, cut));
        chunk = chunk.slice(cut);
      }
      current = chunk;
    }
    for (var i = 0; i < tokens.length; i++) {
      var tok = tokens[i];
      if (!tok) continue;
      var trial = current + tok;
      if (current && doc.getTextWidth(trial) > maxWidth) {
        flush();
        if (/^\s+$/.test(tok)) continue;
        if (doc.getTextWidth(tok) > maxWidth) pushHard(tok);
        else current = tok;
      } else {
        current = trial;
      }
    }
    flush();
    return lines.length ? lines : [''];
  }

  function wrapToVisual(doc, text, maxWidth, rtl) {
    var logical = wrapLogical(doc, String(text || ''), maxWidth);
    if (!rtl) return logical;
    return logical.map(function (line) { return toVisual(line, true); });
  }

  function truncateToWidth(doc, text, maxWidth, rtl) {
    text = String(text || '');
    var visual = toVisual(text, rtl);
    if (doc.getTextWidth(visual) <= maxWidth) return visual;
    var ell = '…';
    var logical = text;
    while (logical && doc.getTextWidth(toVisual(logical + ell, rtl)) > maxWidth) {
      logical = logical.slice(0, -1);
    }
    return toVisual(logical ? logical + ell : ell, rtl);
  }

  function arrayBufferToBase64(buffer) {
    var bytes = new Uint8Array(buffer);
    var chunk = 0x8000;
    var parts = [];
    for (var i = 0; i < bytes.length; i += chunk) {
      parts.push(String.fromCharCode.apply(null, bytes.subarray(i, i + chunk)));
    }
    return btoa(parts.join(''));
  }

  function fetchFontBase64(url) {
    if (fontCache[url]) return Promise.resolve(fontCache[url]);
    return fetch(url)
      .then(function (r) { if (!r.ok) throw new Error('font unavailable'); return r.arrayBuffer(); })
      .then(function (buf) {
        fontCache[url] = arrayBufferToBase64(buf);
        return fontCache[url];
      });
  }

  function preloadDocumentFonts() {
    if (fontPromise) return fontPromise;
    fontPromise = Promise.all([
      fetchFontBase64(FONT_REGULAR_URL),
      fetchFontBase64(FONT_BOLD_URL)
    ]).then(function (pair) {
      return { regular: pair[0], bold: pair[1] };
    }).catch(function () {
      fontPromise = null;
      return null;
    });
    return fontPromise;
  }

  /**
   * Register the PHINS document TTF family on a jsPDF instance.
   * Chrome-only: does not alter generator data. Falls back silently if
   * the subset fonts are unavailable so English downloads still work.
   */
  function applyDocumentFont(doc) {
    var regular = fontCache[FONT_REGULAR_URL];
    var bold = fontCache[FONT_BOLD_URL];
    if (!regular || !bold || !doc || typeof doc.addFileToVFS !== 'function') {
      return null;
    }
    try {
      doc.addFileToVFS('PhinsDejaVu.ttf', regular);
      doc.addFileToVFS('PhinsDejaVu-Bold.ttf', bold);
      doc.addFont('PhinsDejaVu.ttf', DOCUMENT_FONT, 'normal');
      doc.addFont('PhinsDejaVu-Bold.ttf', DOCUMENT_FONT, 'bold');
      doc.setFont(DOCUMENT_FONT, 'normal');
      return DOCUMENT_FONT;
    } catch (e) {
      return null;
    }
  }

  function useFont(doc, opts, weight) {
    var family = (opts && opts.font) || undefined;
    var style = weight || 'normal';
    try {
      doc.setFont(family, style);
    } catch (e) {
      doc.setFont(undefined, style);
    }
  }

  /**
   * Draw the branded letterhead at the top of the current page.
   * opts: { title, subtitle, meta (array of small lines), margin, rtl, font, tagline }
   * Returns the y coordinate where document content should start.
   */
  function letterhead(doc, opts) {
    opts = opts || {};
    var m = opts.margin || 40;
    var pw = doc.internal.pageSize.getWidth();
    var tw = pw - m * 2;
    var y = m - 6;
    var rtl = !!opts.rtl;
    var align = rtl ? 'right' : 'left';
    var tagline = opts.tagline || (rtl ? BRAND_TAGLINE_HE : BRAND_TAGLINE);
    if (rtl) installRtlPainter(doc);

    // shield emblem + wordmark + tagline
    var textX = rtl ? (pw - m) : m;
    if (logoDataUrl) {
      try {
        var logoX = rtl ? (pw - m - 42) : m;
        doc.addImage(logoDataUrl, 'PNG', logoX, y - 8, 42, 42);
        textX = rtl ? (pw - m - 52) : (m + 52);
      } catch (e) { textX = rtl ? (pw - m) : m; }
    }
    useFont(doc, opts, 'bold');
    doc.setFontSize(21);
    doc.setTextColor(NAVY[0], NAVY[1], NAVY[2]);
    doc.text(BRAND_NAME, textX, y + 12, { align: align });
    useFont(doc, opts, 'normal');
    doc.setFontSize(6.8);
    doc.setTextColor(GREY[0], GREY[1], GREY[2]);
    doc.text(toVisual(tagline, rtl), textX, y + 22, { align: align });
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
      useFont(doc, opts, 'bold');
      doc.setFontSize(17);
      doc.setTextColor(NAVY[0], NAVY[1], NAVY[2]);
      var titleLines = wrapToVisual(doc, opts.title, tw, rtl);
      doc.text(titleLines, rtl ? (pw - m) : m, y, { align: align });
      y += titleLines.length * 19;
    }
    if (opts.subtitle) {
      useFont(doc, opts, 'normal');
      doc.setFontSize(9.5);
      doc.setTextColor(BLUE[0], BLUE[1], BLUE[2]);
      var subLines = wrapToVisual(doc, opts.subtitle, tw, rtl);
      doc.text(subLines, rtl ? (pw - m) : m, y, { align: align });
      y += subLines.length * 12 + 2;
    }
    (opts.meta || []).forEach(function (line) {
      useFont(doc, opts, 'normal');
      doc.setFontSize(7.6);
      doc.setTextColor(GREY[0], GREY[1], GREY[2]);
      var metaLines = wrapToVisual(doc, line, tw, rtl);
      doc.text(metaLines, rtl ? (pw - m) : m, y, { align: align });
      y += metaLines.length * 10;
    });

    doc.setTextColor(0, 0, 0);
    useFont(doc, opts, 'normal');
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
    var rtl = !!opts.rtl;
    var note = opts.note || (BRAND_NAME + ' — Confidential investor document');
    var pageLabel = opts.pageLabel || 'Page';
    var pageOf = opts.pageOf || 'of';
    var pageCount = doc.getNumberOfPages();
    if (rtl) installRtlPainter(doc);

    for (var p = 1; p <= pageCount; p++) {
      doc.setPage(p);

      // running header (continuation pages only)
      if (p > 1 && opts.title) {
        var hy = 24;
        useFont(doc, opts, 'bold');
        doc.setFontSize(7.5);
        doc.setTextColor(NAVY[0], NAVY[1], NAVY[2]);
        var titleX = rtl ? (pw - m) : m;
        if (logoDataUrl) {
          try {
            var hx = rtl ? (pw - m - 13) : m;
            doc.addImage(logoDataUrl, 'PNG', hx, hy - 10, 13, 13);
            titleX = rtl ? (pw - m - 17) : (m + 17);
          } catch (e) { titleX = rtl ? (pw - m) : m; }
        }
        doc.text(
          truncateToWidth(doc, opts.title, pw - m * 2 - 80, rtl),
          titleX,
          hy,
          rtl ? { align: 'right' } : undefined
        );
        doc.setDrawColor(GOLD[0], GOLD[1], GOLD[2]);
        doc.setLineWidth(0.9);
        doc.line(m, hy + 5, pw - m, hy + 5);
      }

      // footer: gold hairline · emblem · note · page number
      doc.setDrawColor(GOLD[0], GOLD[1], GOLD[2]);
      doc.setLineWidth(0.9);
      doc.line(m, ph - 30, pw - m, ph - 30);
      useFont(doc, opts, 'normal');
      doc.setFontSize(6.8);
      doc.setTextColor(GREY[0], GREY[1], GREY[2]);
      var noteX = rtl ? (pw - m) : m;
      if (logoDataUrl) {
        try {
          var fx = rtl ? (pw - m - 11) : m;
          doc.addImage(logoDataUrl, 'PNG', fx, ph - 26, 11, 11);
          noteX = rtl ? (pw - m - 15) : (m + 15);
        } catch (e) { noteX = rtl ? (pw - m) : m; }
      }
      var pageText = pageLabel + ' ' + p + ' ' + pageOf + ' ' + pageCount;
      doc.text(
        truncateToWidth(doc, note, pw - m * 2 - 80, rtl),
        noteX,
        ph - 18,
        rtl ? { align: 'right' } : undefined
      );
      doc.text(pageText, rtl ? m : (pw - m), ph - 18, { align: rtl ? 'left' : 'right' });
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
    BRAND_TAGLINE_HE: BRAND_TAGLINE_HE,
    DOCUMENT_FONT: DOCUMENT_FONT,
    CONTINUATION_TOP: CONTINUATION_TOP,
    preload: preload,
    preloadDocumentFonts: preloadDocumentFonts,
    applyDocumentFont: applyDocumentFont,
    letterhead: letterhead,
    finalize: finalize,
    installRtlPainter: installRtlPainter,
    disableJsPdfAutoBidi: disableJsPdfAutoBidi,
    toVisual: toVisual,
    wrapToVisual: wrapToVisual
  };

  // Start fetching the logo immediately so it is ready by first download.
  preload();
})();
