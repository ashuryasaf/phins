/*
 * Pitch dashboard sign-out and idle clock (#pitch-top).
 *
 * Thirty minutes without pointer, key, or scroll activity signs the viewer
 * out. Logout and the idle close call POST /api/pitch-dashboard/logout, which
 * revokes the presented session and expires the viewing cookies. Meeting
 * diary, investor config, and other browser notes are left in place.
 *
 * The server cap is 30 minutes. A share opening with a shorter idle is used
 * when POST /api/pitch-dashboard/session reports it. A quiet tab does not
 * refresh the server clock.
 */
(function () {
  "use strict";

  var IDLE_CAP_MS = 30 * 60 * 1000;
  var IDLE_MS = IDLE_CAP_MS;
  var WARN_MS = 60 * 1000;
  var lastActivity = Date.now();
  var lastBeat = 0;
  var leaving = false;

  function token() {
    try {
      return localStorage.getItem("phins_auth_token") ||
        localStorage.getItem("phins_token") ||
        sessionStorage.getItem("phins_token") ||
        sessionStorage.getItem("phins_auth_token") || "";
    } catch (e) {
      return "";
    }
  }

  function authHeaders() {
    var headers = { "Content-Type": "application/json" };
    var bearer = token();
    if (bearer) headers.Authorization = "Bearer " + bearer;
    return headers;
  }

  function clearClientAuth() {
    var keys = ["phins_auth_token", "phins_token"];
    keys.forEach(function (key) {
      try { localStorage.removeItem(key); } catch (e) {}
      try { sessionStorage.removeItem(key); } catch (e) {}
    });
    try { sessionStorage.removeItem("username"); } catch (e) {}
  }

  function applyIdle(seconds) {
    var n = Number(seconds);
    if (!n || n < 60) return;
    if (n > 30 * 60) n = 30 * 60;
    IDLE_MS = n * 1000;
    var note = document.getElementById("pitch-idle-note");
    if (note) note.textContent = "Idle timeout " + Math.round(n / 60) + " min";
  }

  function endView() {
    if (leaving) return;
    leaving = true;
    var button = document.getElementById("pitch-logout");
    if (button) button.disabled = true;
    var warn = document.getElementById("pitch-idle-warn");
    if (warn) {
      warn.hidden = false;
      warn.textContent = "Signing out…";
    }
    fetch("/api/pitch-dashboard/logout", {
      method: "POST",
      credentials: "same-origin",
      headers: authHeaders(),
      body: "{}"
    }).finally(function () {
      clearClientAuth();
      window.location.replace("/pitch-dashboard.html");
    });
  }

  function markActivity() {
    if (leaving || document.hidden) return;
    lastActivity = Date.now();
    var warn = document.getElementById("pitch-idle-warn");
    if (warn) warn.hidden = true;
  }

  function idleFor() {
    return Date.now() - lastActivity;
  }

  function checkIdle() {
    if (leaving) return;
    var idle = idleFor();
    if (idle >= IDLE_MS) {
      endView();
      return;
    }
    var warn = document.getElementById("pitch-idle-warn");
    if (!warn) return;
    if (idle >= IDLE_MS - WARN_MS) {
      var left = Math.max(1, Math.ceil((IDLE_MS - idle) / 1000));
      warn.hidden = false;
      warn.textContent = "Still there? This view closes in " + left + "s without activity.";
    } else {
      warn.hidden = true;
    }
  }

  function beat(active) {
    if (leaving) return;
    fetch("/api/pitch-dashboard/session", {
      method: "POST",
      credentials: "same-origin",
      headers: authHeaders(),
      body: JSON.stringify({ active: !!active })
    }).then(function (response) {
      if (response.status === 401) {
        endView();
        return null;
      }
      return response.ok ? response.json() : null;
    }).then(function (body) {
      if (body && body.idle_timeout_seconds) applyIdle(body.idle_timeout_seconds);
    }).catch(function () {});
  }

  ["pointerdown", "keydown", "scroll", "touchstart"].forEach(function (name) {
    window.addEventListener(name, markActivity, { passive: true, capture: true });
  });
  document.addEventListener("visibilitychange", checkIdle);
  window.addEventListener("focus", checkIdle);
  setInterval(checkIdle, 1000);
  setInterval(function () {
    if (leaving || document.hidden) return;
    if (idleFor() > 60000) return;
    if (Date.now() - lastBeat < 55000) return;
    lastBeat = Date.now();
    beat(true);
  }, 15000);

  var button = document.getElementById("pitch-logout");
  if (button) {
    button.addEventListener("click", function (event) {
      event.preventDefault();
      endView();
    });
  }
  window.logout = endView;
  beat(true);
})();
