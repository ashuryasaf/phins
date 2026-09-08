/* ============================================================================
 * PHINS Scenario Lab — branded investor / regulator PDF generator
 * ----------------------------------------------------------------------------
 * Full pack (default): live Scenario Lab snapshot, investor story, readiness
 * scores, and — where passed in — the canonical Israel book.
 *
 * Regulator brief (opts.variant === 'regulator'): research only. Product frame,
 * market-readiness scores, public-evidence matrix, and source register.
 * Never attaches a business plan, Israel book, seed/valuation, or lab TAM/GWP.
 *
 * Data-integrity contract:
 *   • Public evidence strings are copied verbatim from marketData / sourceRegistry.
 *   • Israel book figures are the pinned planning-basis identity (ILS 4,518,
 *     25% PHINS take, persistency in-force). They are labeled as planning
 *     assumptions, never as reported public statistics.
 *   • This module does not recompute, round, or blend those identities.
 *   • Chrome (logo, gradient bands, gold/navy rules, fonts) is branding only.
 *   • Hebrew edition uses regulator-grade wording and never pastes English
 *     lab notes (mode / reinsurance / interpretation / insight) into the PDF.
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
      pool: 'Premium pool (lab calibration)',
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
      phinsTake: 'PHINS MGA take',
      insuranceTake: 'Insurance take',
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
      ilBookLead: 'Pinned identity used across the Investor Meeting section. Distinct from the adjustable TAM snapshot above. The table below is the source of record for premium, take rates, in-force, and the 1 January 2027 sales clock.',
      year: 'Year',
      eoy: 'EoY in-force',
      avgIf: 'Avg in-force',
      riskGwp: 'Risk GWP (ILS)',
      phinsRev: 'PHINS net revenue (ILS)',
      insRev: 'Insurance take (ILS)',
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
      dist: 'Distribution: Israel first; USA and Canada for private and employer channels; Portugal as EU Solvency II gateway; Sweden, broader Europe and Japan for top-up; UAE/GCC for capital-light partnerships.',
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
      dataMap: 'Three data layers — do not mix',
      dataMapLead: 'Every figure in this document belongs to one layer. Mixing them is how insurtech over-promises.',
      layer: 'Layer',
      layerContent: 'What it is',
      layerA: 'Layer A — Locked public evidence',
      layerABody: 'Official quotes, titles and URLs, copied in the source language. Never rewritten by lab sliders or by the Israel book.',
      layerB: 'Layer B — Adjustable TAM snapshot (this lab)',
      layerBBody: 'Lives mode: addressable lives × attach rate × planning premium. Premium-share mode: lab premium pool × PHINS target share. Israel TAM default and the live formula are tabulated below. This is a calibration, not the investor-meeting book.',
      layerC: 'Layer C — Pinned Israel book (Investor Meeting)',
      layerCBody: 'Pinned Investor Meeting identity. Average in-force × table risk premium = risk GWP. Take rates, in-force counts, and the sales clock are tabulated below and do not follow lab sliders.',
      ilIdentity: 'Israel book identity (Layer C) — values only',
      ilIdentityPremium: 'Table annual risk premium',
      ilIdentityTake: 'Premium split (PHINS / licensed carrier)',
      ilIdentityEoy: 'EoY in-force',
      ilIdentityAvg: 'Average in-force',
      ilIdentitySales: 'Sales start',
      ilIdentityChurn: 'Annual churn',
      tamDefault: 'Israel TAM default (Layer B)',
      tamDefaultVal: '5,000,000 × 2.4% × ILS 4,518',
      formulaLead: 'The formula applies to Layer B only. Amounts in this table are the live lab calculation. Do not identify them with the Israel book (Layer C).',
      formula: 'Live scenario formula (Layer B)',
      glossary: 'Working glossary',
      glossTerm: 'Term',
      glossMeaning: 'Meaning in this document',
      glossGwp: 'GWP / risk GWP',
      glossGwpBody: 'Gross written premium on the risk cover. In Layer B this is the lab TAM snapshot; in Layer C it is average in-force × ILS 4,518.',
      glossCeded: 'Ceded premium',
      glossCededBody: 'Premium passed to reinsurance under the quota-share assumption. A planning input until replaced by a live treaty quote.',
      glossAttach: 'Attach rate',
      glossAttachBody: 'Share of the addressable population assumed to take up the product. Planning assumption, not a reported public statistic.',
      glossMga: 'MGA take',
      glossMgaBody: 'On the Israel book, PHINS is modelled as a digital MGA / platform: 25% of risk GWP is PHINS net revenue; 75% is the licensed carrier insurance take.',
      glossIf: 'In-force / average in-force',
      glossIfBody: 'Policies in force at year-end, and the year average used to compute Layer C GWP. Average in-force × 4,518 = risk GWP.',
      close: 'This document is a working assessment. Figures that are not labeled as reported public evidence are PHINS planning assumptions and are not commitments, quotes, or guidance.'
    },
    he: {
      title: 'פינס — תזכיר מעבדת התרחישים למשקיעים ולרגולטור',
      subtitle: 'כיסוי נכות קבועה ברמה סיעודית · ראיות ציבוריות נעולות בשפת המקור · הנחות תכנון ניתנות לכיול ואינן ראיה',
      confidential: 'מסמך עבודה חסוי — למשקיעים ולרגולטור. אינו הצעת מחיר, אינו הנחיה ואינו התחייבות.',
      page: 'עמוד',
      pageOf: 'מתוך',
      footer: 'פינס — מעבדת תרחישים · מסמך משקיעים חסוי',
      integrityBanner: 'שלמות נתונים: כל סכום במסמך שייך לשכבה אחת בלבד. ראיה ציבורית מדווחת נשארת נעולה ומתויגת למקור בשפת הפרסום. הנחות המעבדה ותיק ישראל ממפגש המשקיעים הן שכבות תכנון נפרדות, ואינן נכתבות בחזרה לסטטיסטיקה הציבורית.',
      selectedMarket: 'שוק נבחר במעבדה',
      exported: 'חותמת ייצוא',
      assumptions: 'הנחות התרחיש החי — שכבה ב (כיול מעבדה)',
      outputs: 'תוצאות המודל על הנחות שכבה ב',
      mgaOverlay: 'חלוקת פרמיה במודל MGA לישראל (שיעורים ממפגש המשקיעים)',
      mgaNote: 'פינס אינה מבטח מורשה. בתיק ישראל היא ממודלת כסוכן מנהל כללי דיגיטלי (MGA) / פלטפורמה: 25% מפרמיית הסיכון ברוטו היא הכנסת נטו של פינס; 75% הוא חלק הביטוח של המבטח המורשה. חלוקה זו חלה על ה־GWP החי במעבדה בשיעור תואם, אך בקנה מידה של שכבה ב — לא בקנה המידה של תיק ישראל הקבוע. היא אינה מחליפה את מבחן שיעור המסירה / יחס התביעות / יחס ההוצאות שלמעלה.',
      field: 'שדה',
      value: 'ערך',
      metric: 'מדד',
      mode: 'בסיס התרחיש',
      livesMode: 'תרחיש לפי מספר מבוטחים',
      premiumMode: 'תרחיש לפי חלק ממאגר פרמיה לתכנון',
      addressable: 'אוכלוסיית יעד',
      attach: 'שיעור החדרה',
      annualPremium: 'פרמיה שנתית לתכנון',
      pool: 'מאגר פרמיה לתכנון (מעבדה)',
      share: 'חלק יעד של פינס',
      cession: 'שיעור מסירה לביטוח משנה (השתתפות יחסית)',
      loss: 'יחס תביעות צפוי',
      expense: 'יחס הוצאות תפעול',
      gwp: 'פרמיית סיכון ברוטו (GWP)',
      ceded: 'פרמיה שנמסרה לביטוח משנה',
      net: 'פרמיה נטו שנותרה',
      claims: 'תביעות צפויות',
      opex: 'הוצאות תפעול',
      uw: 'תרומת חיתום',
      margin: 'מרווח נטו על פרמיה שנותרה',
      phinsTake: 'חלק פינס כ־MGA',
      insuranceTake: 'חלק המבטח המורשה',
      story: 'קריאת משקיע: היכן התזה של פינס חזקה ביותר',
      storyLead: 'התרשימים אינם ממציאים עובדות ציבוריות. הם מתרגמים את שכבת הראיות לדירוג פנימי של התאמת שוק, יכולת מימוש פרמיה פרטית, ומוכנות לחוזה ביטוח משנה.',
      thesisIsrael: 'תזת כניסה לשוק',
      thesisIsraelKpi: 'ישראל תחילה',
      thesisIsraelBody: 'סיפור ההשקה הנקי ביותר: עוצמת טיפול ביתי, שוק סיעודי שכבר מחונך למוצר, ומבנה כיסוי — נכות קבועה בטריגר 3+ פעולות יומיום — שלקוח ורגולטור מבינים במהירות.',
      thesisUsa: 'הפוטנציאל הגדול ביותר לפרמיה',
      thesisUsaKpi: 'קנה מידה בארצות הברית',
      thesisUsaBody: 'ארצות הברית נותרת השוק הפרטי המשמעותי ביותר כלכלית אם פינס שומרת על טריגר ליקוי חמור וקפדני, ונמנעת מלשון נכות תעסוקתית רחבה.',
      thesisCa: 'הסמיכות הטובה ביותר להפצה',
      thesisCaKpi: 'קבוצות בקנדה',
      thesisCaBody: 'ערוצי מעסיקים וקבוצות שיוך הופכים את קנדה לאטרקטיבית לשכבת נכות מודרנית, תיאום שירותי טיפול וחזרה לתפקוד — לא למכרז סיעודי קמעונאי בלבד.',
      thesisMe: 'יתד דלת-הון',
      thesisMeKpi: 'המזרח התיכון',
      thesisMeBody: 'יחס שימור מפורסם וזרימת פרמיית בריאות גלויה הופכים את מקבץ איחוד האמירויות / המפרץ לאטרקטיבי למבני פרונטינג, MGA ושותפות.',
      priority: 'לוח עדיפות שווקים',
      prioritySub: 'ציון מורכב מבהירות ביקוש, עומק פרמיה והתאמה תפעולית. אינו סטטיסטי ציבורי חדש.',
      demandMap: 'ביקוש מול מימוש פרמיה פרטית',
      demandMapSub: 'בהירות הביקוש מול בהירות היכולת לגבות פרמיה פרטית.',
      dual: 'עומק מערכת ציבורית מול נגישות פרמיה פרטית',
      dualSub: 'מדוע שווקים מסוימים הם שכבת השלמה ואחרים הם מימוש פרמיה ישיר.',
      readiness: 'מוכנות שוק להשקה',
      readinessSub: 'ציון מוכנות מתוך לוח הניקוד הקיים (התאמה תפעולית, גישה פרטית, ביקוש). אינו סטטיסטי ציבורי חדש.',
      readinessScore: 'מוכנות',
      stage: 'שלב כניסה',
      demand: 'ביקוש',
      monetization: 'מימוש פרמיה',
      publicDepth: 'עומק ציבורי',
      privateAccess: 'גישה פרטית',
      fit: 'התאמה תפעולית',
      stageLaunch: 'מוכן להשקה',
      stageScale: 'הרחבה במשמעת',
      stageGroup: 'קבוצה / קבוצות שיוך',
      stageTopup: 'שכבת השלמה / תיאום שירותים',
      stageCaution: 'זהירות תמחור',
      stagePartner: 'שותפות / דל-הון',
      ilBook: 'תיק ישראל — בסיס התכנון ממפגש המשקיעים',
      ilBookLead: 'זהות תכנונית קבועה המשמשת בכל מקטע מפגש המשקיעים. נפרדת מתמונת ה־TAM הניתנת לכיול במעבדה (שכבה ב). טבלת תיק ישראל שלהלן היא מקור האמת לפרמיה, לשיעורי החלוקה, לפוליסות בתוקף ולשעון המכירות.',
      year: 'שנה',
      eoy: 'פוליסות בתוקף בסוף שנה',
      avgIf: 'ממוצע פוליסות בתוקף',
      riskGwp: 'פרמיית סיכון ברוטו (ש"ח)',
      phinsRev: 'הכנסת נטו פינס (ש"ח)',
      insRev: 'חלק המבטח (ש"ח)',
      seed: 'סבב הקמה (סיד)',
      pre: 'שווי לפני ההשקעה',
      post: 'שווי לאחר ההשקעה',
      specimen: 'דוגמת תמחור (טבלאות מפורסמות)',
      specimenVal: 'Age 42 · life ILS 1,000,000 / disability ILS 250,000 · 0.25 / 0.20 per 1,000 / month · ILS 4,518 / year',
      notes: 'הערות הנהלה וממשל תאגידי',
      modeNote: 'נוסחת התרחיש החי',
      reinsNote: 'הערת ביטוח משנה',
      interp: 'משמעות לפינס',
      product: 'מסגרת המוצר: הטבת נכות קבועה בטריגר 3+ פעולות יומיום (ADL), עם טריגר קוגניטיבי חמור אופציונלי (תשישות נפש) ושכבת תיאום שירותי טיפול. המוצר הוא סיכון טהור: ללא חיסכון, ללא ערך פדיון וללא ערך מסולק.',
      vr: 'שכבת שיקום תעסוקתי: חזרה לתפקוד ושיקום מקצועי לתובעים בגיל עבודה — ניהול תביעה, לא הגדלת פרמיית השיא.',
      dist: 'הפצה: ישראל תחילה; ארצות הברית וקנדה לערוצים פרטיים ומעסיקים; פורטוגל כשער סולבנסי II באיחוד האירופי; שוודיה, אירופה הרחבה ויפן כשכבת השלמה; איחוד האמירויות / המפרץ לשותפויות דלות-הון.',
      actuarial: 'זהירות אקטוארית: לפני הגשה לרשות, יש להחליף את יחסי התרחיש בנתוני היארעות, ביטולים, החלמה, בחירה נגדית והצעות ביטוח משנה ספציפיים למדינה. היחסים במעבדה הם מצייני תכנון.',
      evidence: 'מטריצת ראיות — שכבה א (שפת המקור נשמרת)',
      evidenceNote: 'ציטוטי ביקוש, פרמיה וביטוח משנה נשמרים בשפת המקור כדי שלא יפורפרזו נוסחי הפרסום הרשמי. עמודת המשמעות לפינס מנוסחת בעברית. אין בטבלה זו נתוני תיק ישראל הקבוע.',
      market: 'שוק',
      demandCol: 'אות ביקוש (שפת מקור)',
      premiumCol: 'עוגן פרמיה / הטבה (שפת מקור)',
      reinsCol: 'אות ביטוח משנה (שפת מקור)',
      readCol: 'משמעות לפינס',
      sources: 'מרשם מקורות',
      sourceKey: 'מפתח',
      sourceTitle: 'כותרת המקור (כפי שפורסמה)',
      sourceType: 'סוג מקור',
      sourceStrength: 'עוצמת הראיה',
      sourceUrl: 'כתובת',
      thesis: 'תזת המוצר',
      severity: 'כיסוי אירוע חמור — לא הפסקה שכיחה',
      severityBody: 'לבטח אובדן תפקוד קטסטרופלי ועמיד (נכות קבועה ברמה סיעודית), לא כל הפסקת הכנסה קצרת-טווח.',
      home: 'טיפול ביתי תחילה',
      homeBody: 'ראיות OECD מעדיפות טיפול בבית על פני מוסד. ישראל היא הדוגמה הברורה ביותר במערך זה.',
      vrTitle: 'שיקום תעסוקתי כניהול תביעה',
      vrBody: 'מיון מקצועי ותיאום מעסיקים משפרים את כלכלת התביעה יותר מאשר את פרמיית השיא.',
      treaty: 'ניסוח מוכן לחוזה ביטוח משנה',
      treatyBody: 'טריגר 3+ פעולות יומיום קבוע, תקופות המתנה וראיות הכרעה אובייקטיביות יוצרים מסירה נקיה לחוזה יותר מלשון נכות תעסוקתית רחבה.',
      dataMap: 'שלוש שכבות נתונים — אין לערבב',
      dataMapLead: 'ערבוב השכבות הוא הדרך שבה חברות אינשורטק מבטיחות יותר מדי. כל סכום במסמך מזוהה לשכבה.',
      layer: 'שכבה',
      layerContent: 'מה נכלל ומה אינו נכלל',
      layerA: 'שכבה א — ראיות ציבוריות נעולות',
      layerABody: 'ציטוטים, כותרות וכתובות רשמיות, בשפת המקור. המעבדה ותיק ישראל אינם משכתבים אותן.',
      layerB: 'שכבה ב — תמונת TAM ניתנת לכיול (מעבדה זו)',
      layerBBody: 'תרחיש מבוטחים: אוכלוסיית יעד × שיעור החדרה × פרמיה שנתית לתכנון. תרחיש מאגר: מאגר פרמיה לתכנון × חלק יעד. ברירת המחדל לישראל והנוסחה החיה מפורטות בטבלאות הערכים שלהלן. זה כיול TAM, לא תיק מפגש המשקיעים.',
      layerC: 'שכבה ג — תיק ישראל הקבוע (מפגש המשקיעים)',
      layerCBody: 'זהות תכנונית קבועה ממפגש המשקיעים. ממוצע פוליסות בתוקף כפול פרמיית הסיכון הטבלאית שווה לפרמיית הסיכון ברוטו. שיעורי החלוקה, ספירת הפוליסות ושעון המכירות מופיעים בטבלת הערכים — לא בפסקת הפרוזה. אינה נגררת אחרי מחווני המעבדה.',
      ilIdentity: 'זהות תיק ישראל (שכבה ג) — ערכים בלבד',
      ilIdentityPremium: 'פרמיית סיכון שנתית טבלאית',
      ilIdentityTake: 'חלוקת פרמיה (פינס / מבטח מורשה)',
      ilIdentityEoy: 'פוליסות בתוקף סוף שנה',
      ilIdentityAvg: 'ממוצע פוליסות בתוקף',
      ilIdentitySales: 'תחילת מכירות',
      ilIdentityChurn: 'נטישה שנתית',
      tamDefault: 'ברירת מחדל TAM לישראל (שכבה ב)',
      tamDefaultVal: '5,000,000 × 2.4% × ILS 4,518',
      formulaLead: 'הנוסחה חלה על שכבה ב בלבד. הסכומים בטבלה הם חישוב המעבדה החי. אין לזהותם עם תיק ישראל (שכבה ג).',
      formula: 'נוסחת התרחיש החי (שכבה ב)',
      glossary: 'מילון מונחים במסמך זה',
      glossTerm: 'מונח',
      glossMeaning: 'משמעות במסמך זה',
      glossGwp: 'GWP / פרמיית סיכון ברוטו',
      glossGwpBody: 'פרמיה ברוטו על כיסוי הסיכון. בשכבה ב זה תמונת TAM במעבדה; בשכבה ג זה ממוצע פוליסות בתוקף × 4,518 ש"ח.',
      glossCeded: 'פרמיה שנמסרה',
      glossCededBody: 'פרמיה המועברת לביטוח משנה לפי הנחת השתתפות יחסית. קלט תכנון עד שיוחלף בהצעת חוזה חיה.',
      glossAttach: 'שיעור החדרה',
      glossAttachBody: 'חלק מאוכלוסיית היעד שמונח שירכוש את המוצר. הנחת תכנון, לא סטטיסטי ציבורי מדווח.',
      glossMga: 'חלק MGA',
      glossMgaBody: 'בתיק ישראל פינס ממודלת כסוכן מנהל כללי דיגיטלי: 25% מפרמיית הסיכון ברוטו היא הכנסת נטו של פינס; 75% הוא חלק המבטח המורשה.',
      glossIf: 'פוליסות בתוקף / ממוצע בתוקף',
      glossIfBody: 'מספר פוליסות בסוף שנה, והממוצע השנתי שממנו מחושב GWP בשכבה ג. ממוצע בתוקף × 4,518 = פרמיית סיכון ברוטו.',
      close: 'תזכיר זה הוא הערכת עבודה. סכומים שאינם מסומנים כראיה ציבורית מדווחת הם הנחות תכנון של פינס. הם אינם התחייבות, אינם הצעת מחיר ואינם הנחיה לרשות או למשקיע.'
    }
  };

  var REG_COPY = {
    en: {
      title: 'PHINS — Market-readiness brief for the regulator',
      subtitle: 'Public evidence and market-readiness scores · research only · no business plan attached',
      confidential: 'Research brief for a supervisory authority. Not a filing, not a quote, not a business plan, and not a commitment.',
      footer: 'PHINS — Market-readiness brief · research only',
      integrityBanner: 'Data integrity: this brief contains only the locked public-evidence layer and an internal readiness score derived from it. It does not attach a business plan, the Israel book, a fundraising round, a valuation, or the Scenario Lab TAM snapshot.',
      audience: 'Audience: supervisory / licensing authority — market-readiness research',
      purpose: 'Purpose of this brief',
      purposeLead: 'Show the authority the research basis for market readiness — demand signals, premium and benefit anchors, reinsurance signals, and the product frame — without mixing in commercial planning layers.',
      scopeItem: 'Scope',
      scopeDetail: 'What this brief is',
      scopeIn: 'In scope',
      scopeInBody: 'Product frame (severity trigger, home-care, vocational rehabilitation, treaty wording); internal market-readiness scores; public-evidence matrix in the source language; source register.',
      scopeOut: 'Out of scope',
      scopeOutBody: 'No business plan. No Israel planning book. No seed round, no pre/post-money valuation, no Scenario Lab TAM snapshot, no modelled GWP, and no investor ranking charts.',
      readinessMethod: 'Readiness = 0.4 × operating fit + 0.3 × private access + 0.3 × demand, from the existing scorecard. It is an internal composite, not a reported public statistic and not a supervisory rating.',
      glossAdl: 'Permanent 3+ ADL',
      glossAdlBody: 'A benefit paid when the insured is permanently dependent in three or more activities of daily living, with an optional severe cognitive trigger. Pure risk: no savings, no cash value, no surrender value.',
      glossEvidence: 'Public evidence layer',
      glossEvidenceBody: 'Official quotes in the source language, with title, source type, evidence strength, and URL. Lab sliders do not rewrite them.',
      glossReady: 'Market-readiness score',
      glossReadyBody: 'Internal composite of operating fit, private access, and demand. Not a reported public statistic and not a rating by the authority.',
      glossSource: 'Source language',
      glossSourceBody: 'Demand, premium, and reinsurance quotes stay in the official wording. The PHINS read-through column is in the document language.',
      close: 'This brief is working research for a supervisor. It is not a business plan, not a licensing application, and not a substitute for an actuarial filing or a live reinsurance quote.'
    },
    he: {
      title: 'פינס — תזכיר מוכנות שווקים לרגולטור',
      subtitle: 'ראיות ציבוריות וציוני מוכנות שוק · מחקר בלבד · ללא תכנית עסקית',
      confidential: 'תזכיר מחקר לרשות פיקוח. אינו בקשה, אינו הצעת מחיר, אינו תכנית עסקית ואינו התחייבות.',
      footer: 'פינס — תזכיר מוכנות שווקים · מחקר בלבד',
      integrityBanner: 'שלמות נתונים: תזכיר זה מכיל רק את שכבת הראיות הציבוריות הנעולות וציון מוכנות פנימי הנגזר ממנה. אין כאן תכנית עסקית, אין תיק ישראל, אין סבב גיוס, אין שווי, ואין תמונת TAM מהמעבדה.',
      audience: 'קהל: רשות פיקוח / רישוי — מחקר מוכנות שווקים',
      purpose: 'ייעוד התזכיר',
      purposeLead: 'להציג לרשות את בסיס המחקר למוכנות שווקים — אותות ביקוש, עוגני פרמיה והטבה, אותות ביטוח משנה, ומסגרת המוצר — בלי לצרף תכנית עסקית ובלי לערבב שכבות תכנון מסחריות.',
      scopeItem: 'היקף',
      scopeDetail: 'מה נכלל ומה אינו נכלל',
      scopeIn: 'נכלל',
      scopeInBody: 'מסגרת המוצר (טריגר חומרה, טיפול ביתי, שיקום תעסוקתי, ניסוח לחוזה ביטוח משנה); ציון מוכנות שוק פנימי; מטריצת ראיות ציבוריות בשפת המקור; מרשם מקורות.',
      scopeOut: 'לא נכלל',
      scopeOutBody: 'אין תכנית עסקית. אין תיק ישראל. אין סבב גיוס, אין שווי לפני או אחרי השקעה, אין תמונת TAM מהמעבדה, אין GWP ממודל, ואין תרשימי דירוג משקיעים.',
      readinessMethod: 'מוכנות = 0.4 × התאמה תפעולית + 0.3 × גישה פרטית + 0.3 × ביקוש, מלוח הניקוד הקיים. זה ציון פנימי מורכב, לא סטטיסטי ציבורי מדווח ולא דירוג של הרשות.',
      glossAdl: 'נכות קבועה בטריגר 3+ פעולות יומיום',
      glossAdlBody: 'הטבה המשולמת כאשר המבוטח תלוי באופן קבוע בשלוש פעולות יומיום או יותר, עם טריגר קוגניטיבי חמור אופציונלי. זה סיכון טהור: ללא חיסכון, ללא ערך פדיון וללא ערך מסולק.',
      glossEvidence: 'שכבת ראיות ציבוריות',
      glossEvidenceBody: 'ציטוטים רשמיים בשפת המקור, עם כותרת, סוג מקור, עוצמת ראיה וכתובת. מחווני המעבדה אינם משכתבים אותם.',
      glossReady: 'ציון מוכנות שוק',
      glossReadyBody: 'ציון פנימי מורכב מהתאמה תפעולית, גישה פרטית וביקוש. אינו סטטיסטי ציבורי מדווח ואינו דירוג של הרשות.',
      glossSource: 'שפת מקור',
      glossSourceBody: 'ציטוטי ביקוש, פרמיה וביטוח משנה נשמרים בניסוח הרשמי. עמודת המשמעות לפינס מנוסחת בשפת המסמך.',
      close: 'תזכיר זה הוא מחקר עבודה לרשות. הוא אינו תכנית עסקית, אינו בקשת רישוי, ואינו מחליף הגשה אקטוארית או הצעת ביטוח משנה חיה.'
    }
  };

  var MARKET_NAME_HE = {
    israel: 'ישראל',
    usa: 'ארצות הברית',
    canada: 'קנדה',
    wneurope: 'מערב וצפון אירופה',
    sweden: 'שוודיה',
    middleeast: 'המזרח התיכון',
    japan: 'יפן',
    australia: 'אוסטרליה',
    portugal: 'פורטוגל'
  };

  var SOURCE_TYPE_HE = {
    official: 'רשמי / רשות',
    analysis: 'ניתוח',
    industry: 'איגוד ענפי'
  };

  var EVIDENCE_STRENGTH_HE = {
    'benchmark': 'אמת מידה',
    'direct pdf': 'מסמך PDF ישיר',
    'synthesis': 'סינתזה',
    'industry analysis': 'ניתוח ענפי',
    'market survey': 'סקר שוק',
    'market release': 'פרסום שוק',
    'official release': 'פרסום רשמי',
    'news release': 'הודעה לעיתונות',
    'consumer guide': 'מדריך לצרכן',
    'official summary': 'תקציר רשמי',
    'regulatory letter': 'מכתב רגולטורי',
    'industry release': 'פרסום ענפי',
    'official report': 'דוח רשמי'
  };

  var MARKET_COPY_HE = {
    israel: {
      insight: 'שוק ההשקה הנקי ביותר לכיסוי נכות קבועה דיגיטלי: הציבור מכיר ביטוח סיעודי, לוגיסטיקת טיפול ביתי היא ליבת הצורך, והטיעון למיון בבינה מלאכותית ולתיאום שירותי טיפול מובן מיד ללקוח ולרגולטור.',
      reins: 'יש להסתמך על תנאי חוזה ביטוח משנה מצוטטים, לא על סברת שוק. גילוי ציבורי על שיעור מסירה בסיעוד הישראלי לא אותר במערך הראיות הנוכחי.',
      interp: 'המודל מתאר שכבת כיסוי לנכות קבועה ברמה סיעודית מעל שוק סיעודי שכבר מחונך למוצר. אין לערבב שכבה זו עם תיק ישראל הקבוע ממפגש המשקיעים.'
    },
    usa: {
      insight: 'ההזדמנות המסחרית הפרטית הגדולה ביותר — וגם השוק שבו ניסוח טריגר רופף, בחירה נגדית ומורכבות הגשה עלולים לקרוס את הכלכלה במהירות הגבוהה ביותר.',
      reins: 'שיעורי המסירה הם מצייני תכנון. יש להחליפם בניסוח מוצר מאושר במדינה ובהצעות חוזה ביטוח משנה חיות לפני כל החלטת חיתום ממשית.',
      interp: 'זה השוק הטוב ביותר להוכיח שפינס מסוגלת להפוך טריגר 3+ פעולות יומיום קפדני לסיפור פרמיה ולחוזה ביטוח משנה בר-הרחבה.'
    },
    canada: {
      insight: 'קנדה אטרקטיבית להפצה דרך מעסיקים ואגודות. מוצר פינס צריך להיקרא כשכבת נכות מודרנית ותמיכה בטיפול, לא כמכרז סיעודי קטסטרופלי לקמעונאות בלבד.',
      reins: 'כל הנחת שיעור מסירה היא קלט תכנון של פינס עד שיהיו נתוני בלוק מול OSFI או מול חוזה ספציפי.',
      interp: 'קנדה תומכת בתזת הפצה קבוצתית יותר מאשר בסיפור סיעודי קמעונאי ישיר.'
    },
    wneurope: {
      insight: 'שווקים אלה מאמתים צורך מבני וביקוש לטיפול ביתי. פינס מתאימה כשכבת השלמה, תיאום שירותים או גילוף — לא כתחליף למערכות סיעוד סטטוטוריות.',
      reins: 'גילוי אזורי אינו אחיד. כלכלת החוזה חייבת להיות מבוססת הצעת מחיר וספציפית לשוק.',
      interp: 'אירופה מוכיחה צורך; הכניסה המסחרית תלויה במיקום מוצר צר סביב המערכת הציבורית.'
    },
    sweden: {
      insight: 'שוודיה היא שוק ההשלמה הנורדי הנקי ביותר: עוצמת טיפול ביתי רשמית גבוהה, הוצאת סיעוד עירונית גלויה, ושכבת ביטוח בריאות פרטי מדודה כבר קיימת בערוצי מעסיק וקבוצה. פינס צריכה להצטרף כשכבת נכות קבועה ותיאום טיפול, לא כתחליף למערכת הציבורית.',
      reins: 'אין במערך הראיות הנוכחי אמת מידה מפורסמת לשיעור מסירה בנכות או בסיעוד שוודי. כלכלת החוזה תישאר מבוססת הצעה.',
      interp: 'שוודיה מוכיחה ביקוש נורדי לטיפול ביתי ושכבה פרטית מתונה. הכניסה המסחרית היא סיפור השלמה וערוץ קבוצתי, לא החלפת חובה סטטוטורית.'
    },
    middleeast: {
      insight: 'האזור מתאים למודלי MGA, פרונטינג או שותפות: פינס מביאה הכרעה, מיון בבינה מלאכותית ותפעול דיגיטלי לשוק שכבר מבוסס מסירה ומתווכים.',
      reins: 'בניגוד לשורות אחרות, הנחת המסירה כברירת מחדל קשורה ליחס שימור מפורסם באיחוד האמירויות.',
      interp: 'זו הזדמנות מבנה הון ושותפות תחילה, ועדיין לא השוק הנקי ביותר לנתוני תחלואה.'
    },
    japan: {
      insight: 'יפן היא הוכחה מצוינת להשלמה, להכוונת טיפול ביתי ולתיאום ליקוי חמור; היתד המסחרי הוא משלים ולא יסודי.',
      reins: 'הנחות ביטוח משנה יחולו רק על השכבה המשלימה הפרטית, כי תוכנית הסיעוד הציבורית היא פלטפורמת המימון הדומיננטית.',
      interp: 'יפן מאמתת עוצמת ביקוש ומשמעת תשלום יותר מאשר לכידת פרמיה מסחרית פתוחה.'
    },
    australia: {
      insight: 'אוסטרליה היא שוק אמין רק עם תמחור משמעתי, תקופות המתנה מפורשות ובקרת תביעות חזקה. אין זה מקום לניסוח רופף או לאסטרטגיית צמיחה בכל מחיר.',
      reins: 'סקירת הקיימות של APRA לביטוח נכות (DII) היא אות האזהרה המרכזי: יש להניח תמחור צפוף יותר ותיאבון חוזה נמוך יותר מאשר נרטיב שוק חפוז.',
      interp: 'אוסטרליה אטרקטיבית רק לאחר שניסוח המוצר ומנוע התביעות של פינס הוכחו בשוק אחר.'
    },
    portugal: {
      insight: 'פורטוגל היא נקודת כניסה מחייבת תחת סולבנסי II: אוכלוסייה מזדקנת עם פער סיעודי מתרחב, אימוץ ביטוח בריאות פרטי גדל, יישור רגולטורי לגישה לשוק האיחוד, וכוח עבודה צעיר דיגיטלי שיוצר הזדמנות הפצה למוצר דיגיטלי-ראשון.',
      reins: 'פורטוגל פועלת תחת סולבנסי II. שיעורי המסירה הם הנחות תכנון; יש להחליפם בהגשות מוצר תואמות ASF ובהצעות ביטוח משנה חיות לפני כניסה לשוק.',
      interp: 'פורטוגל היא שוק שער לאיחוד עם רוח גבית דמוגרפית לסיעוד, בגישה של מוצרים דיגיטליים תואמי סולבנסי II אל הפער בין כיסוי SNS הציבורי לבין עלות טיפול פרטי עולה.'
    }
  };

  var STAGE_BY_ID = {
    israel: 'stageLaunch',
    usa: 'stageScale',
    canada: 'stageGroup',
    wneurope: 'stageTopup',
    sweden: 'stageTopup',
    middleeast: 'stagePartner',
    japan: 'stageTopup',
    australia: 'stageCaution',
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

  function marketCopy(row, lang) {
    if (lang === 'he' && MARKET_COPY_HE[row && row.id]) return MARKET_COPY_HE[row.id];
    return {
      insight: stripMarks(row && row.insight),
      reins: stripMarks(row && row.reinsuranceNote),
      interp: stripMarks(row && row.interpretationNote)
    };
  }

  function sourceTypeLabel(value, lang) {
    var key = String(value || 'source');
    if (lang === 'he') return SOURCE_TYPE_HE[key] || key;
    return key;
  }

  function evidenceStrengthLabel(value, lang) {
    var key = String(value || 'reference');
    if (lang === 'he') return EVIDENCE_STRENGTH_HE[key] || key;
    return key;
  }

  async function generate(opts) {
    opts = opts || {};
    var brand = window.PhinsPdfBrand;
    if (!window.jspdf || typeof window.jspdf.jsPDF !== 'function' || !brand) {
      throw new Error('PDF library unavailable');
    }
    var lang = opts.lang === 'he' ? 'he' : 'en';
    var rtl = lang === 'he';
    var isRegulator = opts.variant === 'regulator';
    var C = Object.assign({}, COPY[lang], isRegulator ? (REG_COPY[lang] || {}) : {});
    var payload = opts.payload || {};
    var region = opts.region || {};
    var marketData = opts.marketData || [];
    var sourceRegistry = opts.sourceRegistry || {};
    var ilBook = isRegulator ? null : (opts.ilBook || null);
    var outputs = (payload.outputs) || opts.outputs || {};
    var assumptions = payload.assumptions || {};
    var printedAt = formatExportStamp(opts.printedAt || (payload && payload.exportedAt));

    await brand.preload();
    await brand.preloadDocumentFonts();

    var jsPDF = window.jspdf.jsPDF;
    var doc = new jsPDF({ unit: 'pt', format: 'a4' });
    var font = brand.applyDocumentFont(doc);
    if (rtl) brand.installRtlPainter(doc);
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

    function formulaRows() {
      var mode = payload.mode;
      var lives = integer(assumptions.addressableLives);
      var attach = pct(assumptions.attachRate);
      var prem = money(assumptions.annualPremium, currency);
      var pool = money(assumptions.marketPremiumPool, currency);
      var share = pct(assumptions.targetShare);
      var gwp = money(outputs.grossWrittenPremium, currency);
      var cededPct = pct(assumptions.cessionRate);
      var retainedPct = pct(100 - (Number(assumptions.cessionRate) || 0));
      var ceded = money(outputs.cededPremium, currency);
      var net = money(outputs.netPremium, currency);
      var rows;
      if (mode === 'premium') {
        rows = [
          [C.mode, C.premiumMode],
          [C.pool, pool],
          [C.share, share],
          [C.gwp, pool + ' × ' + share + ' = ' + gwp]
        ];
      } else {
        rows = [
          [C.mode, C.livesMode],
          [C.addressable, lives],
          [C.attach, attach],
          [C.annualPremium, prem],
          [C.gwp, lives + ' × ' + attach + ' × ' + prem + ' = ' + gwp]
        ];
      }
      rows.push([C.cession, cededPct]);
      rows.push([C.ceded, gwp + ' × ' + cededPct + ' = ' + ceded]);
      rows.push([C.net, gwp + ' − ' + ceded + ' = ' + net + ' (' + retainedPct + ')']);
      return rows;
    }

    y = brand.letterhead(doc, {
      margin: m,
      font: font || undefined,
      rtl: rtl,
      tagline: rtl ? brand.BRAND_TAGLINE_HE : brand.BRAND_TAGLINE,
      title: title,
      subtitle: subtitle,
      meta: isRegulator ? [
        stripMarks(C.confidential),
        stripMarks(C.exported + ': ' + printedAt),
        stripMarks(C.audience)
      ] : [
        stripMarks(C.confidential),
        stripMarks(C.exported + ': ' + printedAt),
        stripMarks(C.selectedMarket + ': ' + marketName(region, lang) + ' · ' + currency)
      ]
    });

    band(C.integrityBanner);

    if (isRegulator) {
      heading(C.purpose, 12);
      para(C.purposeLead, 8.5, 12, GREY);
      table(
        [C.scopeItem, C.scopeDetail],
        [
          [C.scopeIn, C.scopeInBody],
          [C.scopeOut, C.scopeOutBody]
        ]
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
      para(C.product, 8.5, 12);
      para(C.vr, 8.5, 12);
      para(C.dist, 8.5, 12);
      para(C.actuarial, 8.5, 12);

      heading(C.readiness, 12);
      para(C.readinessSub, 8, 11, GREY);
      para(C.readinessMethod, 8, 11, GREY);
      marketData.forEach(function (row) {
        var scores = row.investorScores || {};
        hbar(marketName(row, lang), readinessOf(row), colorRgb(scores.color));
      });
      y += 6;
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

      heading(C.evidence, 12);
      para(C.evidenceNote, 8, 11, GREY);
      table(
        [C.market, C.demandCol, C.premiumCol, C.reinsCol, C.readCol],
        marketData.map(function (row) {
          var copy = marketCopy(row, lang);
          return [
            marketName(row, lang),
            stripMarks(row.demand),
            stripMarks(row.premium),
            stripMarks(row.reinsurance),
            copy.insight
          ];
        }),
        { 0: 62, 1: 112, 2: 112, 3: 112, 4: 112 }
      );

      heading(C.sources, 12);
      table(
        [C.sourceKey, C.sourceTitle, C.sourceType, C.sourceStrength, C.sourceUrl],
        Object.keys(sourceRegistry).map(function (key) {
          var src = sourceRegistry[key] || {};
          return [
            key,
            stripMarks(src.title),
            sourceTypeLabel(src.sourceType, lang),
            evidenceStrengthLabel(src.evidenceStrength, lang),
            src.url || ''
          ];
        }),
        { 0: 56, 1: 132, 2: 56, 3: 72, 4: 174 }
      );

      heading(C.glossary, 12);
      table(
        [C.glossTerm, C.glossMeaning],
        [
          [C.glossAdl, C.glossAdlBody],
          [C.glossEvidence, C.glossEvidenceBody],
          [C.glossReady, C.glossReadyBody],
          [C.glossSource, C.glossSourceBody]
        ]
      );

      para(C.close, 8, 11, GREY);
    } else {

    heading(C.dataMap, 12);
    para(C.dataMapLead, 8.5, 12, GREY);
    table(
      [C.layer, C.layerContent],
      [
        [C.layerA, C.layerABody],
        [C.layerB, C.layerBBody],
        [C.layerC, C.layerCBody]
      ]
    );
    if (ilBook) {
      heading(C.ilIdentity, 11);
      table(
        [C.field, C.value],
        [
          [C.ilIdentityPremium, money(ilBook.annualPremium, 'ILS')],
          [C.ilIdentityTake, Math.round((Number(ilBook.phinsTakeRate) || 0) * 100) + '% / ' + Math.round((Number(ilBook.insuranceTakeRate) || 0) * 100) + '%'],
          [C.ilIdentityEoy, '2027: ' + integer(ilBook.eoyPolicies[0]) + ' · 2028: ' + integer(ilBook.eoyPolicies[1]) + ' · 2029: ' + integer(ilBook.eoyPolicies[2])],
          [C.ilIdentityAvg, '2027: ' + integer(ilBook.avgInForce[0]) + ' · 2028: ' + integer(ilBook.avgInForce[1]) + ' · 2029: ' + integer(ilBook.avgInForce[2])],
          [C.ilIdentitySales, '2027-01-01'],
          [C.ilIdentityChurn, pct((Number(ilBook.churn) || 0) * 100)],
          [C.tamDefault, C.tamDefaultVal]
        ]
      );
    }

    heading(C.assumptions, 12);
    var assumptionRows = [
      [C.mode, payload.mode === 'premium' ? C.premiumMode : C.livesMode]
    ];
    if (payload.mode === 'premium') {
      assumptionRows.push([C.pool, money(assumptions.marketPremiumPool, currency)]);
      assumptionRows.push([C.share, pct(assumptions.targetShare)]);
    } else {
      assumptionRows.push([C.addressable, integer(assumptions.addressableLives)]);
      assumptionRows.push([C.attach, pct(assumptions.attachRate)]);
      assumptionRows.push([C.annualPremium, money(assumptions.annualPremium, currency)]);
    }
    assumptionRows.push([C.cession, pct(assumptions.cessionRate)]);
    assumptionRows.push([C.loss, pct(assumptions.lossRatio)]);
    assumptionRows.push([C.expense, pct(assumptions.expenseRatio)]);
    table([C.field, C.value], assumptionRows);

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
          [C.phinsTake, money(gwp * 0.25, 'ILS') + ' · 25%'],
          [C.insuranceTake, money(gwp * 0.75, 'ILS') + ' · 75%']
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
    para(C.formula, 9, 12, NAVY, 'bold');
    para(C.formulaLead, 8.5, 12, GREY);
    table(
      [C.field, C.value],
      formulaRows()
    );
    var selectedCopy = marketCopy(region, lang);
    para(C.reinsNote + ': ' + selectedCopy.reins, 8.5, 12);
    para(C.interp + ': ' + selectedCopy.interp, 8.5, 12);
    para(C.product, 8.5, 12);
    para(C.vr, 8.5, 12);
    para(C.dist, 8.5, 12);
    para(C.actuarial, 8.5, 12);

    heading(C.evidence, 12);
    para(C.evidenceNote, 8, 11, GREY);
    table(
      [C.market, C.demandCol, C.premiumCol, C.reinsCol, C.readCol],
      marketData.map(function (row) {
        var copy = marketCopy(row, lang);
        return [
          marketName(row, lang),
          stripMarks(row.demand),
          stripMarks(row.premium),
          stripMarks(row.reinsurance),
          copy.insight
        ];
      }),
      { 0: 62, 1: 112, 2: 112, 3: 112, 4: 112 }
    );

    heading(C.sources, 12);
    table(
      [C.sourceKey, C.sourceTitle, C.sourceType, C.sourceStrength, C.sourceUrl],
      Object.keys(sourceRegistry).map(function (key) {
        var src = sourceRegistry[key] || {};
        return [
          key,
          stripMarks(src.title),
          sourceTypeLabel(src.sourceType, lang),
          evidenceStrengthLabel(src.evidenceStrength, lang),
          src.url || ''
        ];
      }),
      { 0: 56, 1: 132, 2: 56, 3: 72, 4: 174 }
    );

    heading(C.glossary, 12);
    table(
      [C.glossTerm, C.glossMeaning],
      [
        [C.glossGwp, C.glossGwpBody],
        [C.glossCeded, C.glossCededBody],
        [C.glossAttach, C.glossAttachBody],
        [C.glossMga, C.glossMgaBody],
        [C.glossIf, C.glossIfBody]
      ]
    );

    para(C.close, 8, 11, GREY);
    }

    brand.finalize(doc, {
      margin: m,
      font: font || undefined,
      rtl: rtl,
      title: title,
      note: stripMarks(C.footer),
      pageLabel: C.page,
      pageOf: C.pageOf
    });

    var slug = String((region.name || 'market')).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '') || 'market';
    var filename = isRegulator
      ? ('phins-scenario-lab-readiness-' + lang + '.pdf')
      : ('phins-scenario-lab-' + slug + '-' + lang + '.pdf');
    doc.save(filename);
    return { filename: filename, pages: doc.getNumberOfPages(), lang: lang, variant: isRegulator ? 'regulator' : 'full' };
  }

  window.PhinsScenarioLabPdf = {
    generate: generate,
    readinessOf: readinessOf,
    COPY: COPY,
    REG_COPY: REG_COPY,
    MARKET_COPY_HE: MARKET_COPY_HE
  };
})();
