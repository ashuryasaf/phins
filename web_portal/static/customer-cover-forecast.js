/**
 * Locked tariff for the customer one-pager (face US$150,000).
 * Age curve and base rates are the published risk-reference identity.
 * Savings add-on is 100% of the risk tariff. Wallet credit is 30% of that add-on.
 */
(function (root) {
  var PHINS_CUSTOMER_MODEL = Object.freeze({
    version: "v1.1",
    docDate: "2026-10-26",
    face: 150000,
    primaryAge: 42,
    childAge: 5,
    projectionYears: 10,
    blockYears: 5,
    savingsRate: 1.0,
    walletShare: 0.30,
    lifeBaseRate: 0.25,
    disabilityBaseRate: 0.20,
    coreSlope: 0.015,
    youthAnchorAge: 3,
    youthAnchorFactor: 0.30,
    adultAnchorAge: 25,
    adultAnchorFactor: 1.00,
    seniorSlope1: 0.05,
    seniorSlope2: 0.08,
    bandAge: 65,
    lifeSharePre: 1.0,
    lifeSharePost: 0.25,
    disabilitySharePre: 0.25,
    disabilitySharePost: 1.0,
    mortality: Object.freeze({ 35: 0.00133, 36: 0.00141, 37: 0.00150, 38: 0.00160, 39: 0.00171 }),
    disabilityIncidence: Object.freeze({ 35: 0.00450, 36: 0.00468, 37: 0.00487, 38: 0.00507, 39: 0.00528 }),
    mortalitySeverity: 1.00,
    disabilitySeverity: 0.55
  });

  function round2(v) {
    return Math.round((v + Number.EPSILON) * 100) / 100;
  }
  function round4(v) {
    return Math.round((v + Number.EPSILON) * 10000) / 10000;
  }
  function ageFactor(age, M) {
    if (age <= M.adultAnchorAge) {
      var span = M.adultAnchorAge - M.youthAnchorAge;
      var rise = M.adultAnchorFactor - M.youthAnchorFactor;
      var a = Math.max(M.youthAnchorAge, age);
      return round4(M.youthAnchorFactor + (a - M.youthAnchorAge) * (rise / span));
    }
    if (age <= M.bandAge) {
      return round4(M.adultAnchorFactor + (age - M.adultAnchorAge) * M.coreSlope);
    }
    var f = ageFactor(M.bandAge, M);
    var capped = Math.min(age, 80);
    if (capped <= 75) return round4(f + (capped - M.bandAge) * M.seniorSlope1);
    return round4(f + (75 - M.bandAge) * M.seniorSlope1 + (capped - 75) * M.seniorSlope2);
  }
  function benefitSums(age, M) {
    var post = age >= M.bandAge;
    var lifeSum = M.face * (post ? M.lifeSharePost : M.lifeSharePre);
    var dShare = post ? M.disabilitySharePost : M.disabilitySharePre;
    return { lifeSum: lifeSum, disabilitySum: lifeSum * dShare, post: post };
  }
  function totalMonthly(age, M) {
    var s = benefitSums(age, M);
    var f = ageFactor(age, M);
    return (s.lifeSum / 1000) * M.lifeBaseRate * f
      + (s.disabilitySum / 1000) * M.disabilityBaseRate * f;
  }
  function sumKey(rows, key) {
    var total = 0;
    for (var i = 0; i < rows.length; i++) total += rows[i][key];
    return total;
  }
  function fiveYearBlocks(rows, blockYears) {
    var blocks = [];
    var size = blockYears || 5;
    for (var i = 0; i < rows.length; i += size) {
      var slice = rows.slice(i, i + size);
      var n = slice.length;
      if (!n) break;
      blocks.push({
        fromYear: slice[0].year,
        toYear: slice[n - 1].year,
        fromAge: slice[0].age,
        toAge: slice[n - 1].age,
        years: n,
        averageRisk: round2(sumKey(slice, "risk") / n),
        averageSavings: round2(sumKey(slice, "savings") / n),
        averagePaid: round2(sumKey(slice, "paid") / n),
        averageWallet: round2(sumKey(slice, "walletCredit") / n)
      });
    }
    return blocks;
  }
  function buildCustomerForecast(M, ratesFn, startAge) {
    var origin = startAge == null ? M.primaryAge : startAge;
    var rows = [];
    var cumRisk = 0;
    var cumSav = 0;
    var rawLoss = 0;
    var lossCount = 0;
    var walletBal = 0;
    var savBal = 0;
    for (var yr = 1; yr <= M.projectionYears; yr++) {
      var age = origin + (yr - 1);
      var factor = ageFactor(age, M);
      var sums = benefitSums(age, M);
      var risk = round2(totalMonthly(age, M) * 12);
      var savings = round2(risk * M.savingsRate);
      var paid = round2(risk + savings);
      var walletCredit = round2(savings * M.walletShare);
      var savingsKept = round2(savings - walletCredit);
      walletBal = round2(walletBal + walletCredit);
      savBal = round2(savBal + savingsKept);
      var rates = ratesFn ? ratesFn(age, M) : { qx: null, ix: null };
      var qx = rates.qx;
      var ix = rates.ix;
      var raw = null;
      var eLoss = null;
      if (qx != null && ix != null) {
        raw = qx * sums.lifeSum * M.mortalitySeverity + ix * sums.disabilitySum * M.disabilitySeverity;
        eLoss = round2(raw);
        rawLoss += raw;
        lossCount += 1;
      }
      cumRisk = round2(cumRisk + risk);
      cumSav = round2(cumSav + savings);
      rows.push({
        year: yr,
        age: age,
        factor: factor,
        lifeSum: sums.lifeSum,
        disabilitySum: sums.disabilitySum,
        risk: risk,
        savings: savings,
        paid: paid,
        walletCredit: walletCredit,
        savingsKept: savingsKept,
        walletBalance: walletBal,
        savingsBalance: savBal,
        qx: qx,
        ix: ix,
        expectedLoss: eLoss,
        rateSource: rates.source || ""
      });
    }
    var lossComplete = lossCount === rows.length && cumRisk > 0;
    return {
      startAge: origin,
      rows: rows,
      blocks: fiveYearBlocks(rows, M.blockYears),
      totals: {
        cumulativeRisk: cumRisk,
        cumulativeSavings: cumSav,
        cumulativePaid: round2(cumRisk + cumSav),
        walletBalance: walletBal,
        savingsBalance: savBal,
        cumulativeExpectedLoss: lossComplete ? round2(rawLoss) : null,
        averageLossRatio: lossComplete ? rawLoss / cumRisk : null,
        margin: lossComplete ? 1 - (rawLoss / cumRisk) : null
      }
    };
  }

  root.PHINS_CUSTOMER_MODEL = PHINS_CUSTOMER_MODEL;
  root.buildCustomerForecast = buildCustomerForecast;
  root.phinsCustomerAgeFactor = ageFactor;
})(typeof window !== "undefined" ? window : this);
