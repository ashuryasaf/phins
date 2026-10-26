/* Renders the customer one-pager from the locked forecast and the copy dictionary.
   Numbers are written with textContent. A missing incidence rate stays a dash. */
(function () {
  var lang = window.PHINS_CUSTOMER_LANG || document.documentElement.lang || "en";
  var dictionaries = window.PHINS_CUSTOMER_COPY || {};
  var copy = dictionaries[lang] || dictionaries.en || {};
  var model = window.PHINS_CUSTOMER_MODEL;
  var rates = window.phinsReferenceRates;

  function text(id, value) {
    var node = document.getElementById(id);
    if (node) node.textContent = value;
  }

  document.querySelectorAll("[data-copy]").forEach(function (el) {
    var key = el.getAttribute("data-copy");
    if (copy[key] != null) el.textContent = copy[key];
  });
  if (copy.docTitle) document.title = copy.docTitle;

  function usd(n) {
    if (n == null || !isFinite(n)) return "\u2014";
    var body = Math.abs(n).toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
    return (n < 0 ? "-" : "") + "US$" + body;
  }

  function usdDelta(n) {
    if (n == null || !isFinite(n)) return "\u2014";
    var sign = n > 0 ? "+" : n < 0 ? "-" : "";
    return sign + usd(Math.abs(n));
  }

  function usd3(n) {
    if (n == null || !isFinite(n)) return "\u2014";
    return "US$" + n.toLocaleString("en-US", {
      minimumFractionDigits: 3,
      maximumFractionDigits: 3
    });
  }

  function cell(tag, className, value) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = value;
    return node;
  }

  function identityHolds(forecast) {
    if (!forecast || !forecast.rows.length) return false;
    var totals = forecast.totals;
    if (Math.abs(totals.walletBalance + totals.savingsBalance - totals.cumulativeSavings) > 0.001) return false;
    if (Math.abs(totals.cumulativePaid - (totals.cumulativeRisk + totals.cumulativeSavings)) > 0.001) return false;
    for (var i = 0; i < forecast.rows.length; i++) {
      var row = forecast.rows[i];
      if (row.lifeSum !== model.face) return false;
      if (Math.abs(row.savings - row.risk) > 0.001) return false;
      if (Math.abs(row.paid - (row.risk + row.savings)) > 0.001) return false;
      if (Math.abs((row.walletCredit + row.savingsKept) - row.savings) > 0.001) return false;
      if (row.disabilitySum !== model.face * model.disabilitySharePre) return false;
      if (row.expectedLoss == null) return false;
    }
    return forecast.blocks.length === 2;
  }

  function paintYearOne(forecast) {
    var host = document.getElementById("year1-body");
    if (!host) return;
    host.textContent = "";
    var row = forecast.rows[0];
    var lines = [
      [copy.y1Risk, usd(row.risk), usd3(row.risk / 12) + " " + copy.perMonth],
      [copy.y1Sav, usd(row.savings), copy.perYear],
      [copy.y1Paid, usd(row.paid), copy.perYear],
      [copy.y1Wallet, usd(row.walletCredit), copy.perYear],
      [copy.y1Kept, usd(row.savingsKept), copy.perYear],
      [copy.y1Loss, usd(row.expectedLoss), copy.perYear]
    ];
    lines.forEach(function (line) {
      host.appendChild(cell("span", "k", line[0]));
      host.appendChild(cell("span", "v nums", line[1]));
      host.appendChild(cell("span", "nums", line[2]));
    });
  }

  function paintCells(hostId, forecast) {
    var host = document.getElementById(hostId);
    if (!host) return;
    host.textContent = "";
    forecast.rows.forEach(function (row) {
      var card = document.createElement("div");
      card.className = "fc-cell";
      card.appendChild(cell("div", "yr", copy.thYear + " " + row.year));
      card.appendChild(cell("div", "age", copy.thAge + " " + row.age));
      card.appendChild(cell("div", "prem nums", usd(row.risk)));
      card.appendChild(cell("div", "delta nums", copy.thPaid + " " + usd(row.paid)));
      host.appendChild(card);
    });
  }

  function paintAverages(hostId, forecast) {
    var host = document.getElementById(hostId);
    if (!host) return;
    host.textContent = "";
    forecast.blocks.forEach(function (block, index) {
      var card = document.createElement("div");
      card.className = "avg";
      var range = copy.yearsWord + " " + block.fromYear + "\u2013" + block.toYear
        + " \u00b7 " + copy.agesWord + " " + block.fromAge + "\u2013" + block.toAge;
      card.appendChild(cell("div", "k", copy.avgK));
      card.appendChild(cell("div", "v nums", usd(block.averageRisk)));
      var detail = range + " \u00b7 " + copy.avgPaid + " " + usd(block.averagePaid)
        + " \u00b7 " + copy.avgWallet + " " + usd(block.averageWallet);
      if (index > 0) {
        var prev = forecast.blocks[index - 1];
        detail += " \u00b7 " + copy.avgChange + " " + usdDelta(block.averageRisk - prev.averageRisk)
          + " \u00b7 " + copy.avgPaid + " " + usdDelta(block.averagePaid - prev.averagePaid);
      }
      card.appendChild(cell("div", "s", detail));
      host.appendChild(card);
    });
  }

  function paintTotals(hostId, forecast) {
    var host = document.getElementById(hostId);
    if (!host) return;
    host.textContent = "";
    var totals = forecast.totals;
    var lines = [
      [copy.totRisk, totals.cumulativeRisk],
      [copy.totSav, totals.cumulativeSavings],
      [copy.totPaid, totals.cumulativePaid],
      [copy.totWallet, totals.walletBalance]
    ];
    lines.forEach(function (line) {
      var item = document.createElement("div");
      item.appendChild(cell("div", "", line[0]));
      item.appendChild(cell("strong", "nums", usd(line[1])));
      host.appendChild(item);
    });
  }

  function paintTable(hostId, forecast) {
    var host = document.getElementById(hostId);
    if (!host) return;
    host.textContent = "";
    forecast.rows.forEach(function (row, index) {
      var tr = document.createElement("tr");
      [String(row.year), String(row.age), row.factor.toFixed(4), usd(row.risk), usd(row.savings),
        usd(row.paid), usd(row.walletCredit), usd(row.expectedLoss)].forEach(function (value, col) {
        tr.appendChild(cell("td", col === 0 ? "" : "nums", value));
      });
      host.appendChild(tr);
      if ((index + 1) % model.blockYears === 0) {
        var block = forecast.blocks[(index + 1) / model.blockYears - 1];
        var band = document.createElement("tr");
        band.className = "band";
        var label = copy.avgK + " \u00b7 " + copy.yearsWord + " " + block.fromYear + "\u2013" + block.toYear
          + " \u00b7 " + copy.agesWord + " " + block.fromAge + "\u2013" + block.toAge
          + " \u00b7 " + usd(block.averageRisk)
          + " \u00b7 " + copy.avgPaid + " " + usd(block.averagePaid);
        if (block !== forecast.blocks[0]) {
          var prev = forecast.blocks[forecast.blocks.indexOf(block) - 1];
          label += " \u00b7 " + copy.avgChange + " " + usdDelta(block.averageRisk - prev.averageRisk);
        }
        var td = cell("td", "", label);
        td.colSpan = 8;
        band.appendChild(td);
        host.appendChild(band);
      }
    });
  }

  function paintWorked(forecast) {
    var row = forecast.rows[0];
    var host = document.getElementById("worked-line");
    if (!host || !row) return;
    host.textContent = "";
    host.appendChild(cell("span", "", copy.hYear + " "));
    host.appendChild(cell("span", "nums", row.factor.toFixed(4)));
    host.appendChild(cell("span", "", " \u00b7 "));
    host.appendChild(cell("span", "nums", usd(row.risk)));
    host.appendChild(cell("span", "", " " + copy.perYear + " \u00b7 "));
    host.appendChild(cell("span", "nums", usd3(row.risk / 12)));
    host.appendChild(cell("span", "", " " + copy.perMonth + " \u00b7 "));
    host.appendChild(cell("span", "", copy.y1Loss + " "));
    host.appendChild(cell("span", "nums", usd(row.expectedLoss)));
    host.appendChild(cell("span", "", " \u00b7 "));
    host.appendChild(cell("span", "", copy.totRisk + " "));
    host.appendChild(cell("span", "nums", usd(forecast.totals.cumulativeRisk)));
    host.appendChild(cell("span", "", " \u00b7 "));
    host.appendChild(cell("span", "", copy.thLoss + " "));
    host.appendChild(cell("span", "nums", usd(forecast.totals.cumulativeExpectedLoss)));
  }

  if (!model || typeof window.buildCustomerForecast !== "function" || typeof rates !== "function") {
    text("integrity-stamp", copy.stamp || "");
    return;
  }

  var primary = window.buildCustomerForecast(model, rates, model.primaryAge);
  var child = window.buildCustomerForecast(model, rates, model.childAge);
  var sound = identityHolds(primary) && identityHolds(child);
  paintYearOne(primary);
  paintCells("forecast-42", primary);
  paintAverages("avg-42", primary);
  paintTotals("totals-42", primary);
  paintTable("table-42", primary);
  paintWorked(primary);
  paintCells("forecast-5", child);
  paintAverages("avg-5", child);
  paintTotals("totals-5", child);
  paintTable("table-5", child);
  text("integrity-stamp", sound ? copy.stamp : "integrity check failed");
  var fail = document.getElementById("integrity-fail");
  if (fail) fail.style.display = sound ? "none" : "block";

  var pdfBtn = document.getElementById("btn-download-pdf");
  var printBtn = document.getElementById("btn-print");
  if (printBtn) printBtn.addEventListener("click", function () { window.print(); });
  if (pdfBtn) {
    pdfBtn.addEventListener("click", function () {
      downloadPdf(pdfBtn);
    });
  }

  async function downloadPdf(btn) {
    var original = btn.textContent;
    try {
      if (!window.jspdf || !window.html2canvas) {
        window.print();
        return;
      }
      btn.disabled = true;
      btn.textContent = "PDF";
      var jsPDF = window.jspdf.jsPDF;
      var pdf = new jsPDF({ unit: "mm", format: "a4", orientation: "portrait" });
      var pages = document.querySelectorAll(".page");
      for (var i = 0; i < pages.length; i++) {
        var node = pages[i];
        var canvas = await window.html2canvas(node, {
          scale: 2,
          backgroundColor: "#ffffff",
          useCORS: true,
          logging: false,
          windowWidth: node.scrollWidth,
          onclone: function (clonedDoc) {
            clonedDoc.querySelectorAll('img[src="/phins-logo.svg"]').forEach(function (img) {
              img.src = "/phins-logo.png";
            });
          }
        });
        var img = canvas.toDataURL("image/png");
        var ratio = canvas.width / canvas.height;
        var w = 210;
        var h = 210 / ratio;
        if (h > 297) { h = 297; w = 297 * ratio; }
        if (i > 0) pdf.addPage();
        pdf.addImage(img, "PNG", (210 - w) / 2, (297 - h) / 2, w, h, undefined, "FAST");
      }
      pdf.setProperties({
        title: copy.docTitle || "PHINS customer illustration",
        author: "PHINS",
        subject: "US$150,000 customer point of view, Aspire 26 October 2026",
        creator: "PHINS"
      });
      pdf.save(lang === "he" ? "PHINS-CUST-150K-HE.pdf" : "PHINS-CUST-150K.pdf");
    } catch (err) {
      window.print();
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
  }
})();
