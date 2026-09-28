/* ============================================================================
 * PHINS Scenario Lab — actuarial kernel adapter (browser)
 * ----------------------------------------------------------------------------
 * Same product, same published tables, same pinned FX as
 * services/aspire_scale_identity.py (quote_market). Lives-mode annual
 * premium is this quote.
 * Public evidence is never rewritten.
 * ==========================================================================*/
(function (root) {
  'use strict';

  var FX_USD = {
    ILS: 3.68,
    USD: 1.00,
    CAD: 1.36,
    EUR: 0.92,
    AED: 3.67,
    JPY: 154.50,
    AUD: 1.53,
    SEK: 10.85
  };

  var MARKET_SPECS = {
    israel: { currency: 'ILS', age: 42, ageBasis: 'israel_book_specimen' },
    usa: { currency: 'USD', age: 42, ageBasis: 'israel_book_specimen' },
    canada: { currency: 'CAD', age: 42, ageBasis: 'israel_book_specimen' },
    wneurope: { currency: 'EUR', age: 42, ageBasis: 'israel_book_specimen' },
    middleeast: { currency: 'AED', age: 42, ageBasis: 'israel_book_specimen' },
    japan: { currency: 'JPY', age: 42, ageBasis: 'israel_book_specimen' },
    australia: { currency: 'AUD', age: 42, ageBasis: 'israel_book_specimen' },
    sweden: { currency: 'SEK', age: 42, ageBasis: 'israel_book_specimen' },
    portugal: { currency: 'EUR', age: 42, ageBasis: 'israel_book_specimen' },
    bulgaria: { currency: 'EUR', age: 45, ageBasis: 'nsi_2025_mean_age_45_4' }
  };

  var LIFE_RATE = 0.25;
  var DISABILITY_RATE = 0.20;
  var FACE = 1000000;
  var DISABILITY_SHARE = 0.25;

  function riskReferenceV1Factor(age) {
    var a = parseInt(age, 10);
    if (a <= 25) {
      var anchored = Math.max(3, a);
      return round4(0.30 + (anchored - 3) * ((1.00 - 0.30) / (25 - 3)));
    }
    if (a <= 65) {
      return round4(1.00 + (a - 25) * 0.015);
    }
    var base = riskReferenceV1Factor(65);
    var capped = Math.min(a, 80);
    if (capped <= 75) {
      return round4(base + (capped - 65) * 0.05);
    }
    return round4(base + (75 - 65) * 0.05 + (capped - 75) * 0.08);
  }

  function round4(value) {
    return Math.round(value * 10000) / 10000;
  }

  function round2(value) {
    return Math.round(value * 100) / 100;
  }

  function fxPerIls(currency) {
    var code = String(currency || 'ILS').toUpperCase();
    if (!Object.prototype.hasOwnProperty.call(FX_USD, code)) {
      throw new Error('unpinned Scenario Lab currency: ' + currency);
    }
    return FX_USD[code] / FX_USD.ILS;
  }

  function convertIls(amountIls, currency) {
    return Math.round(Number(amountIls) * fxPerIls(currency));
  }

  function quoteIls(age) {
    var issueAge = parseInt(age, 10);
    if (issueAge >= 65) {
      throw new Error('Scenario Lab kernel quote stays inside issue ages 3–64');
    }
    var factor = riskReferenceV1Factor(issueAge);
    var lifeSum = issueAge >= 65 ? FACE * 0.25 : FACE;
    var disabilitySum = issueAge >= 65 ? lifeSum : FACE * DISABILITY_SHARE;
    var lifeMonthly = (lifeSum / 1000) * LIFE_RATE * factor;
    var disabilityMonthly = (disabilitySum / 1000) * DISABILITY_RATE * factor;
    var totalMonthly = lifeMonthly + disabilityMonthly;
    return {
      age: issueAge,
      ageFactor: factor,
      ilsMonthly: round2(totalMonthly),
      ilsAnnual: round2(totalMonthly * 12)
    };
  }

  function quoteMarket(marketId, options) {
    var spec = MARKET_SPECS[marketId];
    if (!spec) {
      throw new Error('unknown Scenario Lab market: ' + marketId);
    }
    var age = options && options.age != null ? options.age : spec.age;
    var raw = quoteIls(age);
    var local = convertIls(raw.ilsAnnual, spec.currency);
    return {
      marketId: marketId,
      currency: spec.currency,
      age: raw.age,
      ageBasis: spec.ageBasis,
      ageFactor: raw.ageFactor,
      lifeRatePer1000: LIFE_RATE,
      disabilityRatePer1000: DISABILITY_RATE,
      faceIls: FACE,
      disabilityFaceIls: FACE * DISABILITY_SHARE,
      ilsAnnual: raw.ilsAnnual,
      ilsMonthly: raw.ilsMonthly,
      localAnnual: local,
      fxPerIls: fxPerIls(spec.currency),
      pricingSource: 'pricing_kernel',
      tableId: 'risk_reference_v1',
      layer: 'phins_planning',
      writesPublicEvidence: false
    };
  }

  function describe(quote) {
    return (
      'Kernel ' + quote.tableId +
      ' · age ' + quote.age +
      ' · f=' + quote.ageFactor.toFixed(3) +
      ' · ILS ' + quote.ilsAnnual.toLocaleString('en-US') +
      ' → ' + quote.currency + ' ' + quote.localAnnual.toLocaleString('en-US') +
      ' · planning FX ' + quote.fxPerIls.toFixed(4) +
      ' · not a public statistic'
    );
  }

  root.PhinsScenarioLabKernel = {
    FX_USD: FX_USD,
    MARKET_SPECS: MARKET_SPECS,
    riskReferenceV1Factor: riskReferenceV1Factor,
    quoteIls: quoteIls,
    quoteMarket: quoteMarket,
    convertIls: convertIls,
    describe: describe
  };
}(window));
