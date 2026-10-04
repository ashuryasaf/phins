/**
 * Shared incidence lookup for the public risk one-pagers.
 *
 * Ages listed on the locked profile keep those rates. Every other age uses
 * the default PHINS kernel V2.0 bracket (rate per 1,000 / 1,000). The age
 * curve is not applied a second time. An age outside every bracket is
 * null, never a silent zero.
 *
 * The live actuary dashboard reads the active store through
 * build_risk_reference. This file is the same identity for the static
 * presentations, which cannot see an uploaded table.
 */
(function (root) {
  var PUBLISHED_Q = { 35: 0.00133, 36: 0.00141, 37: 0.00150, 38: 0.00160, 39: 0.00171 };
  var PUBLISHED_I = { 35: 0.00450, 36: 0.00468, 37: 0.00487, 38: 0.00507, 39: 0.00528 };
  var KERNEL_Q = [
    { age_min: 0, age_max: 30, rate_per_1000: 0.5 },
    { age_min: 30, age_max: 40, rate_per_1000: 1.2 },
    { age_min: 40, age_max: 50, rate_per_1000: 2.5 },
    { age_min: 50, age_max: 60, rate_per_1000: 5.0 },
    { age_min: 60, age_max: 70, rate_per_1000: 12.0 },
    { age_min: 70, age_max: 80, rate_per_1000: 30.0 },
    { age_min: 80, age_max: 120, rate_per_1000: 75.0 },
  ];
  var KERNEL_I = [
    { age_min: 0, age_max: 30, rate_per_1000: 2.0 },
    { age_min: 30, age_max: 40, rate_per_1000: 4.0 },
    { age_min: 40, age_max: 50, rate_per_1000: 8.0 },
    { age_min: 50, age_max: 60, rate_per_1000: 15.0 },
    { age_min: 60, age_max: 70, rate_per_1000: 30.0 },
    { age_min: 70, age_max: 80, rate_per_1000: 50.0 },
    { age_min: 80, age_max: 120, rate_per_1000: 80.0 },
  ];

  function bracket(table, age) {
    for (var i = 0; i < table.length; i += 1) {
      var row = table[i];
      if (row.age_min <= age && age < row.age_max) return row.rate_per_1000 / 1000;
    }
    return null;
  }

  function listed(table, age) {
    if (!table || table[age] == null || table[age] === '') return null;
    var n = Number(table[age]);
    return Number.isFinite(n) ? n : null;
  }

  function phinsReferenceRates(age, model) {
    var qTable = (model && model.mortality) || PUBLISHED_Q;
    var iTable = (model && model.disabilityIncidence) || PUBLISHED_I;
    var publishedQ = listed(qTable, age);
    var publishedI = listed(iTable, age);
    var qx = publishedQ != null ? publishedQ : bracket(KERNEL_Q, age);
    var ix = publishedI != null ? publishedI : bracket(KERNEL_I, age);
    var qSource = publishedQ != null ? 'published_profile' : (qx != null ? 'kernel_table' : 'unavailable');
    var iSource = publishedI != null ? 'published_profile' : (ix != null ? 'kernel_table' : 'unavailable');
    var source = qSource === iSource ? qSource : (qSource + '/' + iSource);
    return { age: age, qx: qx, ix: ix, source: source };
  }

  root.phinsReferenceRates = phinsReferenceRates;
})(typeof window !== 'undefined' ? window : this);
