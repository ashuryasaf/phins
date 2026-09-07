/* ============================================================================
 * PHINS Scenario Lab — branded investor / regulator PDF generator
 * ----------------------------------------------------------------------------
 * Renders the live Scenario Lab snapshot (assumptions + modeled outputs) plus
 * the on-page investor story, market-readiness scores, and — where relevant —
 * the canonical Israel book from the Investor Meeting section.
 *
 * Data-integrity contract:
 *   • Public evidence strings are copied verbatim from marketData / sourceRegistry.
 *   • Israel book figures are the pinned planning-basis identity (ILS 4,518,
 *     25% PHINS take, persistency in-force). They are labeled as planning
 *     assumptions, never as reported public statistics.
 *   • This module does not recompute, round, or blend those identities.
 *   • Chrome (logo, gradient bands, gold/navy rules, fonts) is branding only.
 * ==========================================================================*/
(function () {
  'use strict';

  var NAVY = [14, 47, 99];
  var GOLD = [201, 160, 78];
  var BLUE = [13, 71, 161];
  var BLUE_MID = [21, 101, 192];
  var GREEN = [46, 125, 50];
  var AMBER = [184, 137, 59];
  var RED = [198, 40, 40];
  var GREY = [91, 107, 130];
  var SLATE = [51, 65, 85];

  var COPY = {
    en: {
      title: 'PHINS Scenario Lab — Market Assessment',
      subtitle: 'Board-grade severity-layer assessment · public evidence locked · planning assumptions adjustable',
      confidential: 'Confidential investor and regulator working document',
      page: 'Page',
      pageOf: 'of',
      footer: 'PHINS — Scenario Lab · Confidential investor document',
      integrityBanner: 'Data integrity: reported public evidence stays locked and source-tagged. PHINS scenario assumptions and the Israel book planning basis are separate layers and are never written back into public statistics.',
      selectedMarket: 'Selected market snapshot',
      exported: 'Export timestamp',
      assumptions: 'Scenario assumptions (PHINS planning layer)',
      outputs: 'Current modeled outputs',
      mgaOverlay: 'Israel MGA overlay (investor-meeting take rates)',
      mgaNote: 'PHINS is modelled as a digital MGA / platform on the Israel book: 25% of risk GWP is PHINS net revenue; 75% is the licensed carrier insurance take. This overlay does not replace the cession / loss / expense stress test above.',
      field: 'Field',
      value: 'Value',
      metric: 'Metric',
      mode: 'Scenario mode',
      livesMode: 'Lives mode',
      premiumMode: 'Premium-share mode',
      addressable: 'Addressable lives',
      attach: 'Attach rate',
      annualPremium: 'Annual premium',
      pool: 'Reported premium pool',
      share: 'PHINS target share',
      cession: 'Cession / quota share',
      loss: 'Expected loss ratio',
      expense: 'Operating expense ratio',
      gwp: 'Gross written premium',
      ceded: 'Ceded premium',
      net: 'Net premium retained',
      claims: 'Expected claims',
      opex: 'Operating expenses',
      uw: 'Underwriting contribution',
      margin: 'Net margin on retained premium',
      phinsTake: 'PHINS MGA take (25%)',
      insuranceTake: 'Insurance take (75%)',
      story: 'A visual investor story: where the PHINS thesis is strongest',
      storyLead: 'These visuals do not invent public facts. They translate the evidence layer into an investor ranking of market fit, monetization capacity, and treaty readiness.',
      thesisIsrael: 'Market entry thesis',
      thesisIsraelKpi: 'Israel first',
      thesisIsraelBody: 'The cleanest launch story combines home-care intensity, known LTC behaviour, and a product structure that customers and regulators can understand quickly.',
      thesisUsa: 'Largest premium upside',
      thesisUsaKpi: 'USA scale',
      thesisUsaBody: 'The U.S. remains the most economically meaningful private market if PHINS preserves a strict severe-impairment trigger and avoids broad disability wording.',
      thesisCa: 'Best distribution adjacency',
      thesisCaKpi: 'Canada groups',
      thesisCaBody: 'Employer and affinity channels make Canada compelling for modernized disability, care-navigation, and return-to-function overlays.',
      thesisMe: 'Capital-light wedge',
      thesisMeKpi: 'Middle East',
      thesisMeBody: 'Published retention dynamics and visible health premium flow make the UAE/GCC cluster attractive for fronting, MGA, and partnership structures.',
      priority: 'Market priority scorecard',
      prioritySub: 'Composite visual based on demand clarity, premium depth, and operating fit.',
      demandMap: 'Demand vs. monetization',
      demandMapSub: 'Demand clarity (left) versus private monetization clarity (right).',
      dual: 'Public system depth vs. private premium accessibility',
      dualSub: 'Why some markets are top-up plays and others are direct monetization.',
      readiness: 'Market readiness',
      readinessSub: 'Launch readiness from existing scorecard inputs (fit, private access, demand). Not a new public statistic.',
      readinessScore: 'Readiness',
      stage: 'Stage',
      demand: 'Demand',
      monetization: 'Monetization',
      publicDepth: 'Public depth',
      privateAccess: 'Private access',
      fit: 'Operating fit',
      stageLaunch: 'Launch-ready',
      stageScale: 'Scale with discipline',
      stageGroup: 'Group / affinity',
      stageTopup: 'Top-up / orchestration',
      stageCaution: 'Pricing caution',
      stagePartner: 'Partnership / capital-light',
      ilBook: 'Canonical Israel book — investor meeting planning basis',
      ilBookLead: 'Pinned identity used across the Investor Meeting section. Distinct from the adjustable TAM snapshot above. Sales from 1 January 2027. Table-driven ILS 4,518 risk premium. PHINS 25% / insurance 75%. Annual churn 8%.',
      year: 'Year',
      eoy: 'EoY in-force',
      avgIf: 'Avg in-force',
      riskGwp: 'Risk GWP (ILS)',
      phinsRev: 'PHINS net revenue 25% (ILS)',
      insRev: 'Insurance take 75% (ILS)',
      seed: 'Seed / build round',
      pre: 'Pre-money valuation',
      post: 'Post-money valuation',
      specimen: 'Specimen (published tables)',
      specimenVal: 'Age 42 · life ILS 1,000,000 / disability ILS 250,000 · life 0.25 / disability 0.20 per ILS 1,000 / month · ILS 4,518 / year',
      notes: 'Executive and governance notes',
      modeNote: 'Mode note',
      reinsNote: 'Reinsurance note',
      interp: 'Interpretation',
      product: 'Product frame: Permanent 3+ ADL benefit with optional severe cognitive trigger and care-navigation layer.',
      vr: 'VR layer: return-to-function and vocational rehabilitation for working-age claimants.',
      dist: 'Distribution: Israel first; USA and Canada for private and employer channels; Portugal as EU Solvency II gateway; Europe and Japan for top-up; UAE/GCC for capital-light partnerships.',
      actuarial: 'Actuarial caution: before filing, replace scenario ratios with country-specific incidence, lapse, recovery, selection, and reinsurance quote data.',
      evidence: 'Evidence matrix (reported public layer — source language preserved)',
      evidenceNote: 'Public quotes are kept in their source language so official wording is not paraphrased. PHINS read-through remains in the document language.',
      market: 'Market',
      demandCol: 'Demand signal',
      premiumCol: 'Premium / benefit anchor',
      reinsCol: 'Reinsurance signal',
      readCol: 'PHINS read-through',
      sources: 'Source register',
      sourceKey: 'Key',
      sourceTitle: 'Source title',
      sourceType: 'Type',
      sourceStrength: 'Evidence strength',
      sourceUrl: 'URL',
      thesis: 'Product thesis',
      severity: 'Severity over frequency',
      severityBody: 'Insure catastrophic and durable loss of function, not every short-duration income interruption.',
      home: 'Home-care first',
      homeBody: 'OECD evidence favors home-based care. Israel is the clearest example.',
      vrTitle: 'VR as claim management',
      vrBody: 'Vocational triage and employer coordination improve loss economics more than they change top-line premium.',
      treaty: 'Reinsurance-ready design',
      treatyBody: 'A strict permanent 3+ ADL trigger, waiting periods, and objective adjudication artifacts create a better treaty handoff than broad occupational disability wording.',
      close: 'This document is a working assessment. Figures that are not labeled as reported public evidence are PHINS planning assumptions and are not commitments, quotes, or guidance.'
    },
    he: {
      title: 'מעבדת התרחישים של פינס — הערכת שוק',
      subtitle: 'הערכת שכבת חומרה לדירקטוריון · ראיות ציבוריות נעולות · הנחות תכנון ניתנות לכיול',
      confidential: 'מסמך עבודה חסוי למשקיעים ולרגולטורים',
      page: 'עמוד',
      pageOf: 'מתוך',
      footer: 'פינס — מעבדת תרחישים · מסמך משקיעים חסוי',
      integrityBanner: 'שלמות נתונים: ראיות ציבוריות מדווחות נשארות נעולות ומתויגות למקור. הנחות תרחיש של פינס ובסיס התכנון של ספר ישראל הם שכבות נפרדות ואינם נכתבים בחזרה לסטטיסטיקה הציבורית.',
      selectedMarket: 'שוק נבחר',
      exported: 'חותמת ייצוא',
      assumptions: 'הנחות תרחיש (שכבת תכנון של פינס)',
      outputs: 'תוצרים ממודלים נוכחיים',
      mgaOverlay: 'שכבת MGA לישראל (שיעורי לקיחה ממפגש המשקיעים)',
      mgaNote: 'פינס ממודלת כ-MGA דיגיטלי / פלטפורמה בספר ישראל: 25% מפרמיית הסיכון ברוטו היא הכנסת נטו של פינס; 75% הוא חלק הביטוח של המבטח המורשה. שכבה זו אינה מחליפה את מבחן הוויתור / נזק / הוצאות שלמעלה.',
      field: 'שדה',
      value: 'ערך',
      metric: 'מדד',
      mode: 'בסיס תרחיש',
      livesMode: 'מצב חיים',
      premiumMode: 'מצב חלק-פרמיה',
      addressable: 'חיים ברי-הגעה',
      attach: 'שיעור הצמדה',
      annualPremium: 'פרמיה שנתית',
      pool: 'מאגר פרמיה מדווח',
      share: 'חלק יעד של פינס',
      cession: 'ויתור / השתתפות יחסית',
      loss: 'יחס נזק צפוי',
      expense: 'יחס הוצאות תפעול',
      gwp: 'פרמיה ברוטו שנכתבה',
      ceded: 'פרמיה מותרת',
      net: 'פרמיה נטו שנותרה',
      claims: 'תביעות צפויות',
      opex: 'הוצאות תפעול',
      uw: 'תרומת חיתום',
      margin: 'מרווח נטו על פרמיה שנותרה',
      phinsTake: 'חלק MGA של פינס (25%)',
      insuranceTake: 'חלק ביטוח (75%)',
      story: 'סיפור משקיע חזותי: היכן התזה של פינס חזקה ביותר',
      storyLead: 'הוויזואלים אינם ממציאים עובדות ציבוריות. הם מתרגמים את שכבת הראיות לדירוג משקיעים של התאמת שוק, יכולת מונטיזציה ומוכנות לחוזה ביטוח משנה.',
      thesisIsrael: 'תזת כניסה לשוק',
      thesisIsraelKpi: 'ישראל תחילה',
      thesisIsraelBody: 'סיפור ההשקה הנקי ביותר משלב עוצמת טיפול ביתי, התנהגות LTC מוכרת, ומבנה מוצר שלקוחות ורגולטורים מבינים במהירות.',
      thesisUsa: 'הפוטנציאל הגדול ביותר לפרמיה',
      thesisUsaKpi: 'קנה מידה בארה"ב',
      thesisUsaBody: 'ארה"ב נותרת השוק הפרטי המשמעותי ביותר כלכלית אם פינס שומרת על טריגר פגיעה חמורה וקפדני ונמנעת מלשון נכות רחבה.',
      thesisCa: 'הסמיכות הטובה ביותר להפצה',
      thesisCaKpi: 'קבוצות בקנדה',
      thesisCaBody: 'ערוצי מעסיקים ואפיניות הופכים את קנדה לאטרקטיבית לשכבות נכות מודרניות, ניווט טיפול וחזרה לתפקוד.',
      thesisMe: 'יתד דלת-הון',
      thesisMeKpi: 'המזרח התיכון',
      thesisMeBody: 'דינמיקת שימור מפורסמת וזרימת פרמיית בריאות נראית הופכות את מקבץ איחוד האמירויות / המפרץ לאטרקטיבי למבני פרונטינג, MGA ושותפות.',
      priority: 'לוח ניקוד עדיפות שוק',
      prioritySub: 'ויזואל מורכב על בסיס בהירות ביקוש, עומק פרמיה והתאמה תפעולית.',
      demandMap: 'ביקוש מול מונטיזציה',
      demandMapSub: 'בהירות ביקוש מול בהירות מונטיזציה פרטית.',
      dual: 'עומק מערכת ציבורית מול נגישות פרמיה פרטית',
      dualSub: 'מדוע שווקים מסוימים הם שכבת השלמה ואחרים הם מונטיזציה ישירה.',
      readiness: 'מוכנות שווקים',
      readinessSub: 'מוכנות השקה מתוך נתוני לוח הניקוד הקיימים (התאמה, גישה פרטית, ביקוש). זה אינו סטטיסטי ציבורי חדש.',
      readinessScore: 'מוכנות',
      stage: 'שלב',
      demand: 'ביקוש',
      monetization: 'מונטיזציה',
      publicDepth: 'עומק ציבורי',
      privateAccess: 'גישה פרטית',
      fit: 'התאמה תפעולית',
      stageLaunch: 'מוכן להשקה',
      stageScale: 'התרחבות עם משמעת',
      stageGroup: 'קבוצה / אפיניות',
      stageTopup: 'השלמה / תזמור',
      stageCaution: 'זהירות תמחור',
      stagePartner: 'שותפות / דל-הון',
      ilBook: 'ספר ישראל הקנוני — בסיס תכנון ממפגש המשקיעים',
      ilBookLead: 'זהות נעוצה המשמשת בכל מקטע מפגש המשקיעים. נפרדת מתמונת ה-TAM הניתנת לכיול שלמעלה. מכירות מ-1 בינואר 2027. פרמיית סיכון טבלאית 4,518 ש"ח. פינס 25% / ביטוח 75%. נטישה שנתית 8%.',
      year: 'שנה',
      eoy: 'בתוקף סוף שנה',
      avgIf: 'ממוצע בתוקף',
      riskGwp: 'פרמיית סיכון ברוטו (ש"ח)',
      phinsRev: 'הכנסת נטו פינס 25% (ש"ח)',
      insRev: 'חלק ביטוח 75% (ש"ח)',
      seed: 'סבב סיד / בניה',
      pre: 'שווי טרום-כסף',
      post: 'שווי לאחר-כסף',
      specimen: 'דגימה (טבלאות מפורסמות)',
      specimenVal: 'גיל 42 · חיים 1,000,000 ש"ח / נכות 250,000 ש"ח · חיים 0.25 / נכות 0.20 לכל 1,000 ש"ח לחודש · 4,518 ש"ח לשנה',
      notes: 'הערות הנהלה וממשל',
      modeNote: 'הערת מצב',
      reinsNote: 'הערת ביטוח משנה',
      interp: 'פרשנות',
      product: 'מסגרת מוצר: הטבת 3+ ADL קבועה עם טריגר קוגניטיבי חמור אופציונלי ושכבת ניווט טיפול.',
      vr: 'שכבת שיקום תעסוקתי: חזרה לתפקוד ושיקום מקצועי לתובעים בגיל עבודה.',
      dist: 'הפצה: ישראל תחילה; ארה"ב וקנדה לערוצים פרטיים ומעסיקים; פורטוגל כשער סולבנסי II באיחוד האירופי; אירופה ויפן להשלמה; איחוד האמירויות / המפרץ לשותפויות דלות-הון.',
      actuarial: 'זהירות אקטוארית: לפני הגשה, יש להחליף יחסי תרחיש בנתוני היארעות, ביטולים, החלמה, בחירה והצעות ביטוח משנה ספציפיים למדינה.',
      evidence: 'מטריצת ראיות (שכבה ציבורית מדווחת — שפת המקור נשמרת)',
      evidenceNote: 'ציטוטים ציבוריים נשמרים בשפת המקור כדי לא לפרפראז את נוסח הפרסום הרשמי. קריאת הרוחב של פינס מופיעה בשפת המסמך.',
      market: 'שוק',
      demandCol: 'אות ביקוש',
      premiumCol: 'עוגן פרמיה / הטבה',
      reinsCol: 'אות ביטוח משנה',
      readCol: 'קריאת רוחב של פינס',
      sources: 'מרשם מקורות',
      sourceKey: 'מפתח',
      sourceTitle: 'כותרת מקור',
      sourceType: 'סוג',
      sourceStrength: 'עוצמת ראיה',
      sourceUrl: 'כתובת',
      thesis: 'תזת המוצר',
      severity: 'חומרה על פני תדירות',
      severityBody: 'לבטח אובדן תפקוד קטסטרופלי ועמיד, לא כל הפסקת הכנסה קצרת-טווח.',
      home: 'טיפול ביתי תחילה',
      homeBody: 'ראיות OECD מעדיפות טיפול ביתי. ישראל היא הדוגמה הברורה ביותר.',
      vrTitle: 'שיקום תעסוקתי כניהול תביעה',
      vrBody: 'מיון מקצועי ותיאום מעסיקים משפרים כלכלת נזק יותר מאשר את פרמיית השיא.',
      treaty: 'עיצוב מוכן לביטוח משנה',
      treatyBody: 'טריגר 3+ ADL קבוע, תקופות המתנה וראיות הכרעה אובייקטיביות יוצרים מסירה טובה יותר לחוזה מאשר לשון נכות תעסוקתית רחבה.',
      close: 'מסמך זה הוא הערכת עבודה. נתונים שאינם מסומנים כראיה ציבורית מדווחת הם הנחות תכנון של פינס ואינם התחייבות, הצעת מחיר או הנחיה.'
    }
  };

  var MARKET_NAME_HE = {
    israel: 'ישראל',
    usa: 'ארצות הברית',
    canada: 'קנדה',
    wneurope: 'מערב וצפון אירופה',
    middleeast: 'המזרח התיכון',
    japan: 'יפן',
    australia: 'אוסטרליה',
    albania: 'אלבניה',
    portugal: 'פורטוגל'
  };

  var STAGE_BY_ID = {
    israel: 'stageLaunch',
    usa: 'stageScale',
    canada: 'stageGroup',
    wneurope: 'stageTopup',
    middleeast: 'stagePartner',
    japan: 'stageTopup',
    australia: 'stageCaution',
    albania: 'stagePartner',
    portugal: 'stageTopup'
  };

  function readinessOf(row) {
    var s = row.investorScores || {};
    return Math.round((Number(s.fit || 0) * 0.4) + (Number(s.privateAccess || 0) * 0.3) + (Number(s.demand || 0) * 0.3));
  }

  function colorRgb(name) {
    if (name === 'green') return GREEN;
    if (name === 'amber') return AMBER;
    if (name === 'red') return RED;
    return BLUE_MID;
  }

  function stripMarks(text) {
    return String(text || '')
      .replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}\u{200D}]/gu, '')
      .replace(/[✓✔✕✖★☆►▸•●■□▪▫→←↑↓⚠︎️]/g, '')
      .replace(/\s{2,}/g, ' ')
      .trim();
  }

  function formatExportStamp(raw) {
    var d = raw ? new Date(raw) : new Date();
    if (isNaN(d.getTime())) d = new Date();
    function pad(n) { return n < 10 ? '0' + n : String(n); }
    return d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate())
      + ' ' + pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()) + ' UTC';
  }

  function money(value, currency) {
    var n = Number.isFinite(value) ? value : 0;
    try {
      return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: currency || 'USD',
        maximumFractionDigits: 0
      }).format(n);
    } catch (e) {
      return n.toLocaleString('en-US', { maximumFractionDigits: 0 }) + ' ' + (currency || '');
    }
  }

  function integer(value) {
    return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(Number(value) || 0);
  }

  function pct(value) {
    return (Number(value) || 0).toFixed(1) + '%';
  }

  function marketName(row, lang) {
    if (lang === 'he' && MARKET_NAME_HE[row.id]) return MARKET_NAME_HE[row.id];
    return stripMarks(row.name);
  }

  async function generate(opts) {
    opts = opts || {};
    var brand = window.PhinsPdfBrand;
    if (!window.jspdf || typeof window.jspdf.jsPDF !== 'function' || !brand) {
      throw new Error('PDF library unavailable');
    }
    var lang = opts.lang === 'he' ? 'he' : 'en';
    var rtl = lang === 'he';
    var C = COPY[lang];
    var payload = opts.payload || {};
    var region = opts.region || {};
    var marketData = opts.marketData || [];
    var sourceRegistry = opts.sourceRegistry || {};
    var ilBook = opts.ilBook || null;
    var outputs = (payload.outputs) || opts.outputs || {};
    var assumptions = payload.assumptions || {};
    var printedAt = formatExportStamp(opts.printedAt || (payload && payload.exportedAt));

    await brand.preload();
    await brand.preloadDocumentFonts();

    var jsPDF = window.jspdf.jsPDF;
    var doc = new jsPDF({ unit: 'pt', format: 'a4' });
    var font = brand.applyDocumentFont(doc);
    var pw = doc.internal.pageSize.getWidth();
    var ph = doc.internal.pageSize.getHeight();
    var m = 40;
    var tw = pw - m * 2;
    var y = m;
    var align = rtl ? 'right' : 'left';
    var xText = rtl ? (pw - m) : m;

    function setFace(weight) {
      try { doc.setFont(font || undefined, weight || 'normal'); }
      catch (e) { doc.setFont(undefined, weight || 'normal'); }
    }

    function vis(text) {
      text = stripMarks(text);
      return rtl ? brand.toVisual(text, true) : text;
    }

    function linesOf(text, width) {
      return brand.wrapToVisual(doc, stripMarks(text), width, rtl);
    }

    function ensure(h) {
      if (y + h > ph - 48) {
        doc.addPage();
        y = brand.CONTINUATION_TOP;
      }
    }

    function para(text, size, gap, color, weight) {
      size = size || 9;
      gap = gap || 12;
      setFace(weight || 'normal');
      doc.setFontSize(size);
      if (color) doc.setTextColor(color[0], color[1], color[2]);
      else doc.setTextColor(SLATE[0], SLATE[1], SLATE[2]);
      var lines = linesOf(text, tw);
      var bh = lines.length * gap;
      ensure(bh + 4);
      doc.text(lines, xText, y, { align: align });
      y += bh + 4;
      doc.setTextColor(0, 0, 0);
    }

    function heading(text, size) {
      size = size || 13;
      ensure(size + 22);
      doc.setFillColor(GOLD[0], GOLD[1], GOLD[2]);
      var barW = 18;
      var barX = rtl ? (pw - m - barW) : m;
      doc.rect(barX, y - 10, barW, 4, 'F');
      doc.setFillColor(NAVY[0], NAVY[1], NAVY[2]);
      var navyX = rtl ? (pw - m - barW) : m;
      doc.rect(navyX, y - 6, barW, 1.2, 'F');
      setFace('bold');
      doc.setFontSize(size);
      doc.setTextColor(NAVY[0], NAVY[1], NAVY[2]);
      var lines = linesOf(text, tw - 8);
      doc.text(lines, xText, y + 8, { align: align });
      y += lines.length * (size + 4) + 10;
      doc.setTextColor(0, 0, 0);
    }

    function band(text) {
      var lines = linesOf(text, tw - 20);
      var h = Math.max(36, lines.length * 11 + 16);
      ensure(h + 8);
      doc.setFillColor(11, 31, 63);
      doc.roundedRect(m, y, tw, h, 6, 6, 'F');
      doc.setFillColor(GOLD[0], GOLD[1], GOLD[2]);
      if (rtl) doc.rect(pw - m - 5, y, 5, h, 'F');
      else doc.rect(m, y, 5, h, 'F');
      setFace('normal');
      doc.setFontSize(8);
      doc.setTextColor(247, 226, 160);
      doc.text(lines, rtl ? (pw - m - 14) : (m + 14), y + 14, { align: align });
      y += h + 12;
      doc.setTextColor(0, 0, 0);
    }

    function table(head, body, colW) {
      if (typeof doc.autoTable !== 'function') return;
      ensure(48);
      setFace('normal');
      doc.setFontSize(8);
      var headRow = rtl ? head.slice().reverse() : head;
      var bodyRows = rtl ? body.map(function (r) { return r.slice().reverse(); }) : body;
      var columnStyles = {};
      if (colW) {
        var keys = Object.keys(colW);
        keys.forEach(function (k) {
          var idx = rtl ? (head.length - 1 - Number(k)) : Number(k);
          columnStyles[idx] = { cellWidth: colW[k] };
        });
      }
      var nCols = headRow.length;
      var widths = [];
      for (var ci = 0; ci < nCols; ci++) {
        widths[ci] = (columnStyles[ci] && columnStyles[ci].cellWidth) || (tw / nCols);
      }
      function visCell(text, width) {
        return linesOf(text, Math.max(36, width - 16)).join('\n');
      }
      doc.autoTable({
        startY: y,
        margin: { left: m, right: m },
        head: [headRow.map(function (cell, idx) { return visCell(cell, widths[idx]); })],
        body: bodyRows.map(function (row) {
          return row.map(function (cell, idx) { return visCell(cell, widths[idx]); });
        }),
        styles: {
          font: font || undefined,
          fontSize: 8,
          cellPadding: 5,
          overflow: rtl ? 'hidden' : 'linebreak',
          valign: 'top',
          halign: rtl ? 'right' : 'left',
          textColor: SLATE,
          lineColor: [219, 228, 240],
          lineWidth: 0.4
        },
        headStyles: {
          fillColor: NAVY,
          textColor: [255, 255, 255],
          fontStyle: 'bold',
          font: font || undefined,
          halign: rtl ? 'right' : 'left'
        },
        alternateRowStyles: { fillColor: [248, 250, 252] },
        columnStyles: columnStyles
      });
      y = (doc.lastAutoTable && doc.lastAutoTable.finalY) ? doc.lastAutoTable.finalY + 14 : y + 14;
    }

    function kpiBoxes(items) {
      var cols = 3;
      var gap = 8;
      var boxW = (tw - gap * (cols - 1)) / cols;
      var boxH = 52;
      for (var i = 0; i < items.length; i++) {
        if (i % cols === 0) ensure(boxH + 10);
        var col = i % cols;
        var drawCol = rtl ? (cols - 1 - col) : col;
        var bx = m + drawCol * (boxW + gap);
        if (col === 0 && i > 0) y += boxH + gap;
        doc.setFillColor(248, 250, 252);
        doc.setDrawColor(GOLD[0], GOLD[1], GOLD[2]);
        doc.setLineWidth(0.7);
        doc.roundedRect(bx, y, boxW, boxH, 6, 6, 'FD');
        setFace('normal');
        doc.setFontSize(6.6);
        doc.setTextColor(GREY[0], GREY[1], GREY[2]);
        doc.text(vis(items[i].label), rtl ? (bx + boxW - 8) : (bx + 8), y + 14, { align: align });
        setFace('bold');
        doc.setFontSize(9.5);
        doc.setTextColor(NAVY[0], NAVY[1], NAVY[2]);
        var valLines = linesOf(items[i].value, boxW - 16);
        doc.text(valLines, rtl ? (bx + boxW - 8) : (bx + 8), y + 30, { align: align });
      }
      y += boxH + 14;
      doc.setTextColor(0, 0, 0);
    }

    function hbar(label, score, rgb) {
      ensure(22);
      setFace('normal');
      doc.setFontSize(8);
      doc.setTextColor(SLATE[0], SLATE[1], SLATE[2]);
      var labelW = 118;
      var barX = rtl ? m : (m + labelW);
      var barW = tw - labelW - 36;
      doc.text(vis(label), rtl ? (pw - m) : m, y + 10, { align: align });
      doc.setFillColor(230, 238, 249);
      doc.roundedRect(barX, y, barW, 12, 6, 6, 'F');
      var fill = Math.max(0, Math.min(100, Number(score) || 0)) / 100 * barW;
      doc.setFillColor(rgb[0], rgb[1], rgb[2]);
      if (fill > 0) {
        var fx = rtl ? (barX + barW - fill) : barX;
        doc.roundedRect(fx, y, fill, 12, 6, 6, 'F');
      }
      setFace('bold');
      doc.setFontSize(8);
      doc.setTextColor(NAVY[0], NAVY[1], NAVY[2]);
      doc.text(String(score), rtl ? m : (pw - m), y + 10, { align: rtl ? 'left' : 'right' });
      y += 18;
    }

    var currency = (payload.region && payload.region.currency) || region.currency || 'USD';
    var regionLabel = marketName(region, lang) + ' (' + currency + ')';
    var title = stripMarks(C.title);
    var subtitle = stripMarks(C.subtitle);

    y = brand.letterhead(doc, {
      margin: m,
      font: font || undefined,
      rtl: rtl,
      tagline: rtl ? brand.BRAND_TAGLINE_HE : brand.BRAND_TAGLINE,
      title: title,
      subtitle: subtitle,
      meta: [
        stripMarks(C.confidential),
        stripMarks(C.exported + ': ' + printedAt),
        stripMarks(C.selectedMarket + ': ' + marketName(region, lang) + ' · ' + currency)
      ]
    });

    band(C.integrityBanner);

    heading(C.assumptions, 12);
    table(
      [C.field, C.value],
      [
        [C.mode, payload.mode === 'premium' ? C.premiumMode : C.livesMode],
        [C.addressable, integer(assumptions.addressableLives)],
        [C.attach, pct(assumptions.attachRate)],
        [C.annualPremium, money(assumptions.annualPremium, currency)],
        [C.pool, money(assumptions.marketPremiumPool, currency)],
        [C.share, pct(assumptions.targetShare)],
        [C.cession, pct(assumptions.cessionRate)],
        [C.loss, pct(assumptions.lossRatio)],
        [C.expense, pct(assumptions.expenseRatio)]
      ]
    );

    heading(C.outputs, 12);
    kpiBoxes([
      { label: C.gwp, value: money(outputs.grossWrittenPremium, currency) },
      { label: C.ceded, value: money(outputs.cededPremium, currency) },
      { label: C.net, value: money(outputs.netPremium, currency) },
      { label: C.claims, value: money(outputs.expectedClaims, currency) },
      { label: C.opex, value: money(outputs.operatingExpenses, currency) },
      { label: C.uw, value: money(outputs.underwritingContribution, currency) }
    ]);
    para(C.margin + ': ' + pct(outputs.netMargin), 8.5, 12, GREY);

    if (region.id === 'israel' && Number.isFinite(outputs.grossWrittenPremium)) {
      heading(C.mgaOverlay, 12);
      para(C.mgaNote, 8.5, 12, GREY);
      var gwp = Number(outputs.grossWrittenPremium) || 0;
      table(
        [C.metric, C.value],
        [
          [C.phinsTake, money(gwp * 0.25, 'ILS')],
          [C.insuranceTake, money(gwp * 0.75, 'ILS')]
        ]
      );
    }

    if (ilBook) {
      heading(C.ilBook, 12);
      para(C.ilBookLead, 8.5, 12, GREY);
      var years = ['2027', '2028', '2029'];
      var bookRows = years.map(function (yr, i) {
        return [
          yr,
          integer(ilBook.eoyPolicies[i]),
          integer(ilBook.avgInForce[i]),
          money(ilBook.riskGwp[i], 'ILS'),
          money(ilBook.phinsNetRevenue[i], 'ILS'),
          money(ilBook.insuranceTake[i], 'ILS')
        ];
      });
      table(
        [C.year, C.eoy, C.avgIf, C.riskGwp, C.phinsRev, C.insRev],
        bookRows
      );
      table(
        [C.field, C.value],
        [
          [C.seed, money(ilBook.seedRound, 'ILS')],
          [C.pre, money(ilBook.preMoney, 'ILS')],
          [C.post, money(ilBook.postMoney, 'ILS')],
          [C.specimen, C.specimenVal]
        ]
      );
    }

    heading(C.story, 12);
    para(C.storyLead, 8.5, 12, GREY);
    table(
      [C.field, C.value],
      [
        [C.thesisIsrael + ' — ' + C.thesisIsraelKpi, C.thesisIsraelBody],
        [C.thesisUsa + ' — ' + C.thesisUsaKpi, C.thesisUsaBody],
        [C.thesisCa + ' — ' + C.thesisCaKpi, C.thesisCaBody],
        [C.thesisMe + ' — ' + C.thesisMeKpi, C.thesisMeBody]
      ]
    );

    heading(C.priority, 12);
    para(C.prioritySub, 8, 11, GREY);
    marketData.forEach(function (row) {
      var scores = row.investorScores || {};
      hbar(marketName(row, lang), scores.priority, colorRgb(scores.color));
    });
    y += 6;

    heading(C.demandMap, 12);
    para(C.demandMapSub, 8, 11, GREY);
    marketData.forEach(function (row) {
      var scores = row.investorScores || {};
      hbar(marketName(row, lang) + ' · ' + C.demand, scores.demand, BLUE);
      hbar(marketName(row, lang) + ' · ' + C.monetization, scores.monetization, GREEN);
    });
    y += 6;

    heading(C.dual, 12);
    para(C.dualSub, 8, 11, GREY);
    marketData.forEach(function (row) {
      var scores = row.investorScores || {};
      hbar(marketName(row, lang) + ' · ' + C.publicDepth, scores.publicDepth, [0, 131, 143]);
      hbar(marketName(row, lang) + ' · ' + C.privateAccess, scores.privateAccess, GOLD);
    });
    y += 6;

    heading(C.readiness, 12);
    para(C.readinessSub, 8, 11, GREY);
    var readyRows = marketData.map(function (row) {
      var scores = row.investorScores || {};
      var stageKey = STAGE_BY_ID[row.id] || 'stageTopup';
      return [
        marketName(row, lang),
        String(readinessOf(row)),
        C[stageKey],
        String(scores.fit || 0),
        String(scores.demand || 0),
        String(scores.privateAccess || 0)
      ];
    });
    table(
      [C.market, C.readinessScore, C.stage, C.fit, C.demand, C.privateAccess],
      readyRows
    );

    heading(C.thesis, 12);
    table(
      [C.field, C.value],
      [
        [C.severity, C.severityBody],
        [C.home, C.homeBody],
        [C.vrTitle, C.vrBody],
        [C.treaty, C.treatyBody]
      ]
    );

    heading(C.notes, 12);
    para(C.modeNote + ': ' + stripMarks((opts.modeNote || '')), 8.5, 12);
    para(C.reinsNote + ': ' + stripMarks(region.reinsuranceNote || ''), 8.5, 12);
    para(C.interp + ': ' + stripMarks(region.interpretationNote || ''), 8.5, 12);
    para(C.product, 8.5, 12);
    para(C.vr, 8.5, 12);
    para(C.dist, 8.5, 12);
    para(C.actuarial, 8.5, 12);

    heading(C.evidence, 12);
    para(C.evidenceNote, 8, 11, GREY);
    table(
      [C.market, C.demandCol, C.premiumCol, C.reinsCol, C.readCol],
      marketData.map(function (row) {
        return [
          marketName(row, lang),
          stripMarks(row.demand),
          stripMarks(row.premium),
          stripMarks(row.reinsurance),
          stripMarks(row.insight)
        ];
      }),
      { 0: 62, 1: 112, 2: 112, 3: 112, 4: 112 }
    );

    heading(C.sources, 12);
    table(
      [C.sourceKey, C.sourceTitle, C.sourceType, C.sourceStrength, C.sourceUrl],
      Object.keys(sourceRegistry).map(function (key) {
        var src = sourceRegistry[key] || {};
        return [key, stripMarks(src.title), src.sourceType || 'source', src.evidenceStrength || 'reference', src.url || ''];
      }),
      { 0: 56, 1: 132, 2: 56, 3: 72, 4: 174 }
    );

    para(C.close, 8, 11, GREY);

    brand.finalize(doc, {
      margin: m,
      font: font || undefined,
      rtl: rtl,
      title: title,
      note: stripMarks(C.footer + ' · ' + printedAt),
      pageLabel: C.page,
      pageOf: C.pageOf
    });

    var slug = String((region.name || 'market')).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '') || 'market';
    var filename = 'phins-scenario-lab-' + slug + '-' + lang + '.pdf';
    doc.save(filename);
    return { filename: filename, pages: doc.getNumberOfPages(), lang: lang };
  }

  window.PhinsScenarioLabPdf = {
    generate: generate,
    readinessOf: readinessOf,
    COPY: COPY
  };
})();
