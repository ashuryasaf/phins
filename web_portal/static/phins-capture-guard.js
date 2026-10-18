/* PHINS capture guard. Loaded only on a document that was shown or sent.
   The business-plan protected view has its own copy of these controls. */
(function () {
  var cfg = window.PHINS_CAPTURE_GUARD || {};
  var stamp = String(cfg.stamp || "PHINS confidential");
  var body = document.body;
  if (!body || body.getAttribute("data-phins-guard") === "1") return;
  body.setAttribute("data-phins-guard", "1");

  var style = document.createElement("style");
  style.textContent = [
    "body[data-phins-guard]{user-select:none;-webkit-user-select:none}",
    "body[data-phins-guard] input,body[data-phins-guard] textarea,body[data-phins-guard] canvas{user-select:text;-webkit-user-select:text}",
    "@media print{body[data-phins-guard]{display:none !important}}",
    "#phins-capture-shade{display:none;position:fixed;inset:0;z-index:2147483000;background:#060d1f;color:#f7e2a0;",
    "align-items:center;justify-content:center;text-align:center;padding:32px;font:600 18px/1.4 Inter,sans-serif}",
    "body.phins-capture-blur #phins-capture-shade{display:flex}",
    "body.phins-capture-blur > *:not(#phins-capture-shade){filter:blur(18px)}",
    "#phins-capture-watermark{position:fixed;inset:0;z-index:2147482000;pointer-events:none;overflow:hidden}",
    "#phins-capture-watermark span{position:absolute;color:rgba(201,160,78,.28);font:600 13px Inter,sans-serif;",
    "transform:rotate(-24deg);white-space:nowrap}"
  ].join("");
  document.head.appendChild(style);

  var shade = document.createElement("div");
  shade.id = "phins-capture-shade";
  shade.textContent = "This document is hidden while the window is not in front.";
  body.appendChild(shade);

  var wm = document.createElement("div");
  wm.id = "phins-capture-watermark";
  wm.setAttribute("aria-hidden", "true");
  for (var r = 0; r < 10; r++) {
    for (var c = 0; c < 3; c++) {
      var tile = document.createElement("span");
      tile.textContent = stamp;
      tile.style.left = ((c + (r % 2 ? 0.4 : 0)) * 34) + "%";
      tile.style.top = (r * 12) + "%";
      wm.appendChild(tile);
    }
  }
  body.appendChild(wm);

  function swallow(ev) {
    ev.preventDefault();
    ev.stopPropagation();
    return false;
  }
  ["contextmenu", "copy", "cut", "dragstart"].forEach(function (name) {
    document.addEventListener(name, swallow, true);
  });
  document.addEventListener("selectstart", function (ev) {
    var tag = ev.target && ev.target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "CANVAS") return true;
    return swallow(ev);
  }, true);
  document.addEventListener("keydown", function (ev) {
    var key = (ev.key || "").toLowerCase();
    var mod = ev.ctrlKey || ev.metaKey;
    if (key === "printscreen") {
      swallow(ev);
      try { navigator.clipboard && navigator.clipboard.writeText(""); } catch (e) {}
      return;
    }
    if (mod && ["p", "s", "u", "c", "x", "a"].indexOf(key) >= 0) { swallow(ev); return; }
    if (mod && ev.shiftKey && ["i", "j", "c", "s", "3", "4", "5"].indexOf(key) >= 0) { swallow(ev); return; }
    if (key === "f12") swallow(ev);
  }, true);
  document.addEventListener("keyup", function (ev) {
    if ((ev.key || "").toLowerCase() === "printscreen") {
      try { navigator.clipboard && navigator.clipboard.writeText(""); } catch (e) {}
    }
  }, true);
  try {
    window.print = function () {};
  } catch (e) {}

  function pause() { body.classList.add("phins-capture-blur"); }
  function resume() { body.classList.remove("phins-capture-blur"); }
  window.addEventListener("blur", pause);
  window.addEventListener("focus", resume);
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) pause(); else resume();
  });
  shade.addEventListener("click", function () { window.focus(); resume(); });
})();
