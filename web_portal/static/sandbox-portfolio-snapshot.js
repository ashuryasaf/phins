/**
 * Actuarial sandbox portfolio snapshot.
 *
 * One pure roll-up shared by the Sandbox Insight "Portfolio Snapshot" tab
 * and the CSV / Excel / PDF exports, so those surfaces cannot drift.
 *
 * Premium booked is the annual written premium of in-force policies.
 * Premium billed is invoice face: realized bills already issued, or the
 * in-force monthly premium in the forecast. Expected death and disability
 * are that booked premium times the simulation loss ratio, split by the
 * simulation's mortality / disability claim mix. The mix is normalised so
 * the two parts sum to expected claims exactly.
 *
 * Monthly customer growth compounds the opening active book:
 *   customers(m) = round(N * (1 + g) ^ (m - 1))
 * Forecast claims use the same loss ratio on premium billed (gross). That
 * is the simulator identity (expected claims / annual premium), not a
 * ratio on cash collected. Cash collected is premium billed times the
 * assumed collection rate.
 *
 * The savings add-on is a share of that collected premium and is a
 * liability, not operating cash. Net cash flow is the operating premium
 * (collected minus the savings add-on) minus expected claims, plus the
 * management fee. The fee is a percentage of the savings AUM, so it
 * scales with the book instead of a flat amount.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  root.PhinsSandboxSnapshot = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const COLLECTION_RATE = 0.95;
  const DEFAULT_MORTALITY_SHARE = 0.6;

  function num(value, fallback) {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  }

  function asShare(value) {
    if (value == null || value === '') return null;
    const n = Number(value);
    if (!Number.isFinite(n) || n < 0) return null;
    return n > 1 ? n / 100 : n;
  }

  /**
   * Mortality and disability shares of expected claims, summing to 1.
   * Accepts fractions (0.6) or percents (60). A missing side is the
   * complement. Both missing falls back to the sandbox's historical
   * 60/40 mortality/disability split.
   */
  function claimMix(mortality, disability) {
    let m = asShare(mortality);
    let d = asShare(disability);
    if (m == null && d == null) {
      m = DEFAULT_MORTALITY_SHARE;
      d = 1 - DEFAULT_MORTALITY_SHARE;
    } else if (m == null) {
      d = Math.min(1, d);
      m = Math.max(0, 1 - d);
    } else if (d == null) {
      m = Math.min(1, m);
      d = Math.max(0, 1 - m);
    }
    const sum = m + d;
    if (!(sum > 0)) {
      m = DEFAULT_MORTALITY_SHARE;
      d = 1 - DEFAULT_MORTALITY_SHARE;
    } else {
      m /= sum;
      d /= sum;
    }
    return { mortality: m, disability: d };
  }

  function splitClaims(claims, mix) {
    const death = claims * mix.mortality;
    // Remainder, so death + disability equals claims exactly.
    const disability = claims - death;
    return { death: death, disability: disability };
  }

  function clampShare(value) {
    return Math.min(1, Math.max(0, num(value, 0)));
  }

  function clampFeeRate(value) {
    return Math.min(0.10, Math.max(0, num(value, 0)));
  }

  function clampYield(value) {
    return Math.min(0.5, Math.max(-0.5, num(value, 0)));
  }

  /**
   * One month of the segregated savings fund. Contribution lands first,
   * yield accrues on that base, then the management fee is the annual
   * rate / 12 of the gross AUM. The fee is zero when the rate is zero
   * or the fund is empty, and it doubles when the fund doubles.
   */
  function stepSavingsFund(openingAum, contribution, monthlyYield, monthlyFee) {
    const base = Math.max(0, num(openingAum, 0)) + Math.max(0, num(contribution, 0));
    const yieldAmt = base * monthlyYield;
    const grossAum = base + yieldAmt;
    const managementFee = grossAum * monthlyFee;
    return {
      yield: yieldAmt,
      grossAum: grossAum,
      managementFee: managementFee,
      closingAum: grossAum - managementFee,
    };
  }

  /**
   * Relative management fee on `totalSavings` spread evenly over `periods`
   * monthly contributions. Used for realized sandbox cash, where the
   * bills are a lump rather than the forecast's month-by-month rows.
   */
  function managementFeeOnContributions(totalSavings, periods, opts) {
    const o = opts || {};
    const n = Math.max(0, Math.round(num(periods, 0)));
    const total = Math.max(0, num(totalSavings, 0));
    if (!(n > 0) || !(total > 0)) return { fee: 0, closingAum: 0 };
    const monthlyFee = clampFeeRate(o.managementFeePctOfAum) / 12;
    const monthlyYield = clampYield(o.savingsYieldPct) / 12;
    const monthly = total / n;
    let aum = 0;
    let fee = 0;
    for (let i = 0; i < n; i++) {
      const step = stepSavingsFund(aum, monthly, monthlyYield, monthlyFee);
      fee += step.managementFee;
      aum = step.closingAum;
    }
    return { fee: fee, closingAum: aum };
  }

  /**
   * 1..horizon monthly expectancy. Customers compound at growthPct.
   * Claims follow premium billed × loss ratio, then the claim mix.
   */
  function buildForecast(opts) {
    const o = opts || {};
    const startCustomers = Math.max(0, num(o.startCustomers, 0));
    const growthPct = Math.max(0, num(o.growthPct, 0));
    const g = growthPct / 100;
    const ppc = Math.max(0, num(o.premiumPerCustomer, 0));
    const lossRatioPct = Math.max(0, num(o.lossRatioPct, 0));
    const lr = lossRatioPct / 100;
    let horizon = Math.round(num(o.horizon, 60));
    if (!Number.isFinite(horizon)) horizon = 60;
    horizon = Math.max(1, Math.min(60, horizon));
    const collectionRate = o.collectionRate == null
      ? COLLECTION_RATE
      : Math.min(1, Math.max(0, num(o.collectionRate, COLLECTION_RATE)));
    const mix = claimMix(o.mortalityShare, o.disabilityShare);
    const savingsShare = clampShare(o.savingsShare);
    const feeAnnual = o.managementFeePctOfAum == null
      ? 0
      : clampFeeRate(o.managementFeePctOfAum);
    const yieldAnnual = o.savingsYieldPct == null ? 0 : clampYield(o.savingsYieldPct);
    const monthlyFee = feeAnnual / 12;
    const monthlyYield = yieldAnnual / 12;

    const rows = [];
    let accumBilled = 0;
    let accumCollected = 0;
    let accumClaims = 0;
    let accumDeath = 0;
    let accumDisability = 0;
    let accumSavings = 0;
    let accumOperating = 0;
    let accumFee = 0;
    let accumNet = 0;
    let aum = Math.max(0, num(o.openingSavingsAum, 0));
    for (let m = 1; m <= horizon; m++) {
      const customers = Math.round(startCustomers * Math.pow(1 + g, m - 1));
      const premiumBilled = customers * ppc;
      const premiumCollected = premiumBilled * collectionRate;
      const claims = premiumBilled * lr;
      const parts = splitClaims(claims, mix);
      const savingsCollected = premiumCollected * savingsShare;
      const operatingCollected = premiumCollected - savingsCollected;
      const fund = stepSavingsFund(aum, savingsCollected, monthlyYield, monthlyFee);
      aum = fund.closingAum;
      const netCashFlow = operatingCollected - claims + fund.managementFee;
      accumBilled += premiumBilled;
      accumCollected += premiumCollected;
      accumClaims += claims;
      accumDeath += parts.death;
      accumDisability += parts.disability;
      accumSavings += savingsCollected;
      accumOperating += operatingCollected;
      accumFee += fund.managementFee;
      accumNet += netCashFlow;
      rows.push({
        month: m,
        customers: customers,
        premiumBilled: premiumBilled,
        // Collected cash. Older readers used this key for the monthly
        // premium run-rate; it is now billed × the collection rate.
        collectedPremium: premiumCollected,
        savingsCollected: savingsCollected,
        operatingCollected: operatingCollected,
        managementFee: fund.managementFee,
        savingsAum: aum,
        claimsPaid: claims,
        deathPaid: parts.death,
        disabilityPaid: parts.disability,
        netCashFlow: netCashFlow,
        accumBilled: accumBilled,
        accumPremium: accumCollected,
        accumSavings: accumSavings,
        accumOperating: accumOperating,
        accumFee: accumFee,
        accumNet: accumNet,
        accumClaims: accumClaims,
        accumDeath: accumDeath,
        accumDisability: accumDisability,
      });
    }

    const openingMonthlyBilled = startCustomers * ppc;
    return {
      rows: rows,
      mix: mix,
      collectionRate: collectionRate,
      lossRatio: lr,
      lossRatioPct: lossRatioPct,
      growthPct: growthPct,
      horizon: horizon,
      startCustomers: startCustomers,
      premiumPerCustomer: ppc,
      openingMonthlyBilled: openingMonthlyBilled,
      annualisedOpeningBilled: openingMonthlyBilled * 12,
      savingsShare: savingsShare,
      managementFeePctOfAum: feeAnnual,
      savingsYieldPct: yieldAnnual,
    };
  }

  function sumRows(rows, elapsed) {
    const out = {
      horizonBilled: 0,
      horizonCollected: 0,
      horizonClaims: 0,
      horizonDeath: 0,
      horizonDisability: 0,
      horizonSavings: 0,
      horizonOperating: 0,
      horizonFee: 0,
      horizonNet: 0,
      toDateBilled: 0,
      toDateCollected: 0,
      toDateClaims: 0,
      toDateDeath: 0,
      toDateDisability: 0,
      toDateSavings: 0,
      toDateOperating: 0,
      toDateFee: 0,
      toDateNet: 0,
    };
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      const billed = num(r.premiumBilled, 0);
      const collected = num(r.collectedPremium, billed * COLLECTION_RATE);
      const claims = num(r.claimsPaid, 0);
      const death = num(r.deathPaid, 0);
      const disability = num(r.disabilityPaid, claims - death);
      const savings = num(r.savingsCollected, 0);
      const operating = num(r.operatingCollected, collected - savings);
      const fee = num(r.managementFee, 0);
      const net = num(r.netCashFlow, operating - claims + fee);
      out.horizonBilled += billed;
      out.horizonCollected += collected;
      out.horizonClaims += claims;
      out.horizonDeath += death;
      out.horizonDisability += disability;
      out.horizonSavings += savings;
      out.horizonOperating += operating;
      out.horizonFee += fee;
      out.horizonNet += net;
      if ((num(r.month, i + 1)) <= elapsed) {
        out.toDateBilled += billed;
        out.toDateCollected += collected;
        out.toDateClaims += claims;
        out.toDateDeath += death;
        out.toDateDisability += disability;
        out.toDateSavings += savings;
        out.toDateOperating += operating;
        out.toDateFee += fee;
        out.toDateNet += net;
      }
    }
    return out;
  }

  /**
   * Portfolio snapshot. `rows` are the forecast from buildForecast.
   * Realized premium billed / collected and realized death / disability
   * are passed in from the in-memory book; this function does not invent
   * them. The inception invoice (one monthly bill per opening active
   * policy, issued when the sandbox is generated) sits in front of
   * forecast month 1, so expected premium billed to date at elapsed 0
   * equals the opening monthly billed amount.
   */
  function portfolioSnapshot(input) {
    const src = input || {};
    const mix = claimMix(src.mortalityShare, src.disabilityShare);
    const lossRatioPct = Math.max(0, num(src.lossRatioPct, 0));
    const lr = lossRatioPct / 100;
    const annualBooked = Math.max(0, num(src.annualPremiumBooked, 0));
    const expectedClaimsAnnual = annualBooked * lr;
    const annualParts = splitClaims(expectedClaimsAnnual, mix);

    const hasYear1 = src.lossRatioYear1Pct != null && src.lossRatioYear1Pct !== ''
      && Number.isFinite(Number(src.lossRatioYear1Pct));
    const lossRatioYear1Pct = hasYear1 ? Math.max(0, Number(src.lossRatioYear1Pct)) : null;
    const expectedClaimsYear1 = hasYear1 ? annualBooked * (lossRatioYear1Pct / 100) : null;
    const year1Parts = hasYear1 ? splitClaims(expectedClaimsYear1, mix) : null;

    const rows = Array.isArray(src.rows) ? src.rows : [];
    const elapsed = Math.max(0, num(src.monthsElapsed, 0));
    const rolled = sumRows(rows, elapsed);
    const startCustomers = Math.max(0, num(src.startCustomers, 0));
    const ppc = Math.max(0, num(src.premiumPerCustomer, 0));
    const openingMonthlyBilled = startCustomers * ppc;
    const growthPct = Math.max(0, num(src.growthPct, 0));
    const collectionRate = src.collectionRate == null
      ? COLLECTION_RATE
      : Math.min(1, Math.max(0, num(src.collectionRate, COLLECTION_RATE)));

    const premiumBilled = Math.max(0, num(src.premiumBilled, 0));
    const premiumCollected = Math.max(0, num(src.premiumCollected, 0));
    const realizedDeath = Math.max(0, num(src.realizedDeathPaid, 0));
    const realizedDisability = Math.max(0, num(src.realizedDisabilityPaid, 0));
    const realizedCollectionRate = premiumBilled > 0 ? premiumCollected / premiumBilled : 0;

    // Inception bill plus each elapsed forecast month.
    const expectedBilledToDate = openingMonthlyBilled + rolled.toDateBilled;
    const expectedCollectedToDate = openingMonthlyBilled * collectionRate + rolled.toDateCollected;

    const endCustomers = rows.length ? num(rows[rows.length - 1].customers, 0) : 0;
    const month1Customers = rows.length ? num(rows[0].customers, 0) : 0;
    const formulaEnd = rows.length
      ? Math.round(startCustomers * Math.pow(1 + growthPct / 100, rows.length - 1))
      : 0;

    const annualisedOpeningBilled = openingMonthlyBilled * 12;
    const bookedVsBilledGap = annualBooked - annualisedOpeningBilled;

    // Absolute cents plus a tiny relative band so large books still
    // reconcile after ordinary floating-point addition.
    const near = (a, b) => {
      const scale = Math.max(1, Math.abs(a), Math.abs(b));
      return Math.abs(a - b) <= Math.max(0.05, scale * 1e-8);
    };
    const claimsIdentity = near(
      annualParts.death + annualParts.disability,
      expectedClaimsAnnual
    );
    const horizonIdentity = near(
      rolled.horizonDeath + rolled.horizonDisability,
      rolled.horizonClaims
    );
    const collectedIdentity = rows.length === 0 || near(
      rolled.horizonCollected,
      rolled.horizonBilled * collectionRate
    );
    const savingsIdentity = rows.length === 0 || near(
      rolled.horizonSavings + rolled.horizonOperating,
      rolled.horizonCollected
    );
    const netIdentity = rows.length === 0 || near(
      rolled.horizonNet,
      rolled.horizonOperating - rolled.horizonClaims + rolled.horizonFee
    );
    const growthIdentity = rows.length === 0 || formulaEnd === endCustomers;
    const year1Identity = !hasYear1 || near(
      year1Parts.death + year1Parts.disability,
      expectedClaimsYear1
    );

    const snap = {
      annualPremiumBooked: annualBooked,
      openingMonthlyBilled: openingMonthlyBilled,
      annualisedOpeningBilled: annualisedOpeningBilled,
      bookedVsBilledGap: bookedVsBilledGap,
      premiumBilled: premiumBilled,
      expectedBilledToDate: expectedBilledToDate,
      premiumBilledVariance: premiumBilled - expectedBilledToDate,
      premiumCollected: premiumCollected,
      expectedCollectedToDate: expectedCollectedToDate,
      realizedCollectionRate: realizedCollectionRate,
      collectionRate: collectionRate,
      lossRatioPct: lossRatioPct,
      mix: mix,
      expectedDeathAnnual: annualParts.death,
      expectedDisabilityAnnual: annualParts.disability,
      expectedClaimsAnnual: expectedClaimsAnnual,
      hasYear1: hasYear1,
      lossRatioYear1Pct: lossRatioYear1Pct,
      expectedDeathYear1: hasYear1 ? year1Parts.death : null,
      expectedDisabilityYear1: hasYear1 ? year1Parts.disability : null,
      expectedClaimsYear1: expectedClaimsYear1,
      realizedDeathPaid: realizedDeath,
      realizedDisabilityPaid: realizedDisability,
      expectedDeathToDate: rolled.toDateDeath,
      expectedDisabilityToDate: rolled.toDateDisability,
      deathVariance: realizedDeath - rolled.toDateDeath,
      disabilityVariance: realizedDisability - rolled.toDateDisability,
      growthPct: growthPct,
      startCustomers: startCustomers,
      month1Customers: month1Customers,
      endCustomers: endCustomers,
      horizon: rows.length,
      monthsElapsed: elapsed,
      rowsReady: rows.length > 0,
      horizonBilled: rolled.horizonBilled,
      horizonCollected: rolled.horizonCollected,
      horizonClaims: rolled.horizonClaims,
      horizonDeath: rolled.horizonDeath,
      horizonDisability: rolled.horizonDisability,
      horizonSavings: rolled.horizonSavings,
      horizonOperating: rolled.horizonOperating,
      horizonManagementFee: rolled.horizonFee,
      savingsShare: clampShare(src.savingsShare),
      managementFeePctOfAum: src.managementFeePctOfAum == null
        ? 0
        : clampFeeRate(src.managementFeePctOfAum),
      horizonNet: rolled.horizonNet,
      materialized: src.materialized == null ? null : num(src.materialized, 0),
      accepted: src.accepted == null ? null : num(src.accepted, 0),
      checks: {
        claimsIdentity: claimsIdentity,
        horizonIdentity: horizonIdentity,
        collectedIdentity: collectedIdentity,
        savingsIdentity: savingsIdentity,
        netIdentity: netIdentity,
        growthIdentity: growthIdentity,
        year1Identity: year1Identity,
      },
    };
    snap.checks.ok = claimsIdentity && horizonIdentity && collectedIdentity
      && savingsIdentity && netIdentity && growthIdentity && year1Identity;
    return snap;
  }

  function snapshotLines(snap) {
    if (!snap) return [];
    const lines = [
      { section: 'Premium', label: 'Annual premium booked (gross)', value: snap.annualPremiumBooked, kind: 'money' },
      { section: 'Premium', label: 'Opening monthly premium billed', value: snap.openingMonthlyBilled, kind: 'money' },
      { section: 'Premium', label: 'Annualised opening billed (monthly × 12)', value: snap.annualisedOpeningBilled, kind: 'money' },
      { section: 'Premium', label: 'Booked minus annualised billed', value: snap.bookedVsBilledGap, kind: 'money' },
      { section: 'Premium', label: 'Premium billed to date (invoices issued)', value: snap.premiumBilled, kind: 'money' },
      { section: 'Premium', label: 'Expected premium billed to date', value: snap.expectedBilledToDate, kind: 'money' },
      { section: 'Premium', label: 'Premium billed variance (realized − expected)', value: snap.premiumBilledVariance, kind: 'money' },
      { section: 'Premium', label: 'Premiums collected to date', value: snap.premiumCollected, kind: 'money' },
      { section: 'Premium', label: 'Realized collection rate', value: snap.realizedCollectionRate, kind: 'rate' },
      { section: 'Premium', label: 'Assumed collection rate (forecast)', value: snap.collectionRate, kind: 'rate' },
      { section: 'Expected claims', label: 'Loss ratio (claims / booked premium)', value: snap.lossRatioPct, kind: 'points' },
      { section: 'Expected claims', label: 'Expected death paid (annual, on booked premium)', value: snap.expectedDeathAnnual, kind: 'money' },
      { section: 'Expected claims', label: 'Expected disability paid (annual, on booked premium)', value: snap.expectedDisabilityAnnual, kind: 'money' },
      { section: 'Expected claims', label: 'Expected claims (annual = death + disability)', value: snap.expectedClaimsAnnual, kind: 'money' },
    ];
    if (snap.hasYear1) {
      lines.push(
        { section: 'Expected claims', label: 'Loss ratio, year-1 (claims / booked premium)', value: snap.lossRatioYear1Pct, kind: 'points' },
        { section: 'Expected claims', label: 'Expected death paid (year-1, on booked premium)', value: snap.expectedDeathYear1, kind: 'money' },
        { section: 'Expected claims', label: 'Expected disability paid (year-1, on booked premium)', value: snap.expectedDisabilityYear1, kind: 'money' }
      );
    }
    lines.push(
      { section: 'Realized claims', label: 'Realized death paid', value: snap.realizedDeathPaid, kind: 'money' },
      { section: 'Realized claims', label: 'Realized disability paid', value: snap.realizedDisabilityPaid, kind: 'money' },
      { section: 'Realized claims', label: 'Expected death paid to date', value: snap.expectedDeathToDate, kind: 'money' },
      { section: 'Realized claims', label: 'Expected disability paid to date', value: snap.expectedDisabilityToDate, kind: 'money' },
      { section: 'Realized claims', label: 'Death variance (realized − expected to date)', value: snap.deathVariance, kind: 'money' },
      { section: 'Realized claims', label: 'Disability variance (realized − expected to date)', value: snap.disabilityVariance, kind: 'money' },
      { section: 'Lifecycle growth', label: 'Monthly customer growth', value: snap.growthPct, kind: 'points' },
      { section: 'Lifecycle growth', label: 'Opening active customers', value: snap.startCustomers, kind: 'count' },
      { section: 'Lifecycle growth', label: 'Expected customers, month 1', value: snap.month1Customers, kind: 'count' },
      { section: 'Lifecycle growth', label: 'Expected customers, final month', value: snap.endCustomers, kind: 'count' },
      { section: 'Lifecycle growth', label: 'Forecast horizon (months)', value: snap.horizon, kind: 'count' },
      { section: 'Lifecycle growth', label: 'Lifecycle months elapsed', value: snap.monthsElapsed, kind: 'count' },
      { section: 'Lifecycle growth', label: 'Expected premium billed over horizon', value: snap.horizonBilled, kind: 'money' },
      { section: 'Lifecycle growth', label: 'Expected premium collected over horizon', value: snap.horizonCollected, kind: 'money' },
      { section: 'Lifecycle growth', label: 'Expected savings add-on collected over horizon', value: snap.horizonSavings, kind: 'money' },
      { section: 'Lifecycle growth', label: 'Expected operating premium collected over horizon', value: snap.horizonOperating, kind: 'money' },
      { section: 'Lifecycle growth', label: 'Expected management fee income over horizon', value: snap.horizonManagementFee, kind: 'money' },
      { section: 'Lifecycle growth', label: 'Management fee rate (of savings AUM)', value: snap.managementFeePctOfAum, kind: 'rate' },
      { section: 'Lifecycle growth', label: 'Expected death paid over horizon', value: snap.horizonDeath, kind: 'money' },
      { section: 'Lifecycle growth', label: 'Expected disability paid over horizon', value: snap.horizonDisability, kind: 'money' },
      { section: 'Lifecycle growth', label: 'Expected net cash flow over horizon (operating premium − claims + management fee)', value: snap.horizonNet, kind: 'money' }
    );
    return lines;
  }

  return {
    COLLECTION_RATE: COLLECTION_RATE,
    claimMix: claimMix,
    buildForecast: buildForecast,
    managementFeeOnContributions: managementFeeOnContributions,
    portfolioSnapshot: portfolioSnapshot,
    snapshotLines: snapshotLines,
  };
});
