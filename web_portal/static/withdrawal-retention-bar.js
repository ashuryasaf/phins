/*
 * Withdrawal retention bar for customer relations.
 *
 * Lists customers whose health-wallet withdrawal is held, the time left
 * before the bank transfer, and the retention methods the desk can use.
 * Staff record steps and place offers. Only the customer moves the money
 * back; a release or a decline is for admin and accountant.
 */
(function () {
  "use strict";

  const API = "/api/admin/wallet-withdrawals";
  const mount = document.getElementById("withdrawal-retention-bar");
  if (!mount) return;

  const FLAG_TEXT = {
    third_party_account: "Account holder differs from the customer",
    signer_name_differs: "Signed under a different name",
    identity_not_on_file: "No identity on file before this request",
    reversal_seal_pending: "Return recorded, NFT seal pending",
  };
  const STATUS_TEXT = {
    held: "Held", reversed: "Returned to wallet", declined: "Declined", paid_out: "Paid out",
  };

  let board = null;
  let filter = "held";
  let expanded = false;
  let openRow = "";
  let openMethod = "";
  let message = null;
  let timer = null;

  function token() {
    const found = localStorage.getItem("phins_token") || sessionStorage.getItem("authToken") ||
      sessionStorage.getItem("phins_token") || "";
    return String(found || "").trim();
  }

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function money(value) {
    return "$" + Number(value || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function when(value) {
    if (!value) return "";
    const date = new Date(value);
    if (isNaN(date.getTime())) return String(value);
    return date.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  }

  function timeLeft(seconds) {
    if (seconds == null) return "";
    if (seconds <= 0) return "Window ended";
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    if (days) return days + "d " + hours + "h left";
    const minutes = Math.floor((seconds % 3600) / 60);
    return hours ? hours + "h " + minutes + "m left" : minutes + "m left";
  }

  async function call(method, path, body) {
    const headers = { Accept: "application/json" };
    const bearer = token();
    if (bearer) headers.Authorization = "Bearer " + bearer;
    const options = { method: method, headers: headers, credentials: "same-origin" };
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    const response = await fetch(API + path, options);
    let payload = {};
    try { payload = await response.json(); } catch (err) { payload = {}; }
    if (!response.ok) throw { status: response.status, code: payload.code, message: payload.error || "That did not go through." };
    return payload;
  }

  const STYLE = [
    ".wrb{margin:0 0 22px;border-radius:16px;border:1px solid rgba(227,191,111,.55);background:linear-gradient(135deg,#0b1730 0%,#12264d 100%);color:#eaf1ff;font-family:Inter,system-ui,sans-serif;overflow:hidden}",
    ".wrb.quiet{border-color:rgba(127,178,255,.25)}",
    ".wrb-head{display:flex;flex-wrap:wrap;align-items:center;gap:10px 18px;padding:14px 18px;cursor:pointer}",
    ".wrb-flag{display:inline-flex;align-items:center;justify-content:center;min-width:34px;height:34px;padding:0 10px;border-radius:999px;background:#e3bf6f;color:#071022;font-weight:800;font-family:'Space Grotesk',Inter,sans-serif}",
    ".wrb.quiet .wrb-flag{background:rgba(127,178,255,.25);color:#eaf1ff}",
    ".wrb-title{font-family:'Space Grotesk',Inter,sans-serif;font-weight:700;font-size:1.05rem;color:#f7e2a0}",
    ".wrb-sub{font-size:.84rem;color:rgba(234,241,255,.72)}",
    ".wrb-figs{display:flex;flex-wrap:wrap;gap:8px 22px;margin-left:auto;font-size:.84rem;color:rgba(234,241,255,.72)}",
    ".wrb-figs b{display:block;font-family:'Space Grotesk',Inter,sans-serif;font-size:1.05rem;color:#fff}",
    ".wrb-toggle{border:1px solid rgba(227,191,111,.6);background:transparent;color:#f7e2a0;border-radius:10px;width:34px;height:34px;font-size:1.2rem;cursor:pointer}",
    ".wrb-body{padding:0 18px 18px}",
    ".wrb-tabs{display:flex;gap:8px;margin:0 0 12px;flex-wrap:wrap}",
    ".wrb-tab{border:1px solid rgba(127,178,255,.3);background:transparent;color:#eaf1ff;border-radius:999px;padding:5px 14px;font:inherit;font-size:.8rem;cursor:pointer}",
    ".wrb-tab.on{background:#e3bf6f;border-color:#e3bf6f;color:#071022;font-weight:700}",
    ".wrb-row{border:1px solid rgba(127,178,255,.22);border-radius:14px;background:rgba(6,13,31,.45);margin-bottom:10px}",
    ".wrb-row.ready{border-color:rgba(76,214,165,.6)}",
    ".wrb-line{display:grid;grid-template-columns:minmax(150px,1.3fr) minmax(90px,.6fr) minmax(150px,1fr) minmax(130px,.9fr) auto;gap:10px 16px;align-items:center;padding:12px 14px;cursor:pointer}",
    "@media(max-width:820px){.wrb-line{grid-template-columns:1fr 1fr}}",
    ".wrb-name{font-weight:700;color:#fff}",
    ".wrb-id{font-size:.74rem;color:rgba(234,241,255,.6)}",
    ".wrb-amount{font-family:'Space Grotesk',Inter,sans-serif;font-size:1.1rem;color:#f7e2a0}",
    ".wrb-meter{height:6px;border-radius:99px;background:rgba(127,178,255,.2);overflow:hidden;margin-top:5px}",
    ".wrb-meter i{display:block;height:100%;background:linear-gradient(90deg,#e3bf6f,#f7e2a0)}",
    ".wrb-row.ready .wrb-meter i{background:#4cd6a5}",
    ".wrb-small{font-size:.78rem;color:rgba(234,241,255,.72)}",
    ".wrb-pill{display:inline-block;border-radius:999px;padding:2px 10px;font-size:.7rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;background:rgba(227,191,111,.2);color:#f7e2a0}",
    ".wrb-pill.warn{background:rgba(240,120,90,.2);color:#ffb39f}",
    ".wrb-pill.ok{background:rgba(76,214,165,.18);color:#4cd6a5}",
    ".wrb-detail{border-top:1px solid rgba(127,178,255,.18);padding:14px}",
    ".wrb-cols{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);gap:18px}",
    "@media(max-width:820px){.wrb-cols{grid-template-columns:1fr}}",
    ".wrb-h{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:rgba(234,241,255,.6);margin:0 0 8px}",
    ".wrb-methods{display:flex;flex-wrap:wrap;gap:8px}",
    ".wrb-method{border:1px solid rgba(127,178,255,.3);background:rgba(16,31,63,.8);color:#eaf1ff;border-radius:999px;padding:7px 13px;font:inherit;font-size:.82rem;cursor:pointer}",
    ".wrb-method:hover,.wrb-method.on{border-color:#e3bf6f;color:#f7e2a0}",
    ".wrb-method.suggested{border-color:#e3bf6f}",
    ".wrb-method.suggested::after{content:' · suggested';color:#e3bf6f;font-size:.72rem}",
    ".wrb-method:disabled{opacity:.45;cursor:not-allowed}",
    ".wrb-form{margin-top:12px;display:grid;gap:8px}",
    ".wrb-form label{display:grid;gap:4px;font-size:.78rem;color:rgba(234,241,255,.72)}",
    ".wrb-form textarea,.wrb-form input,.wrb-form select{border-radius:10px;border:1px solid rgba(127,178,255,.3);background:rgba(6,13,31,.7);color:#eaf1ff;padding:9px 11px;font:inherit;font-size:.88rem;width:100%;box-sizing:border-box}",
    ".wrb-form textarea{min-height:64px;resize:vertical}",
    ".wrb-btns{display:flex;flex-wrap:wrap;gap:8px;align-items:center}",
    ".wrb-btn{border:0;border-radius:10px;padding:9px 16px;font:inherit;font-size:.84rem;font-weight:700;cursor:pointer;background:linear-gradient(135deg,#f7e2a0,#e3bf6f);color:#071022}",
    ".wrb-btn.ghost{background:transparent;border:1px solid rgba(127,178,255,.35);color:#eaf1ff;font-weight:600}",
    ".wrb-btn.danger{background:transparent;border:1px solid rgba(240,120,90,.6);color:#ffb39f}",
    ".wrb-btn:disabled{opacity:.45;cursor:not-allowed}",
    ".wrb-trail{list-style:none;margin:0;padding:0;display:grid;gap:8px;max-height:260px;overflow:auto}",
    ".wrb-trail li{font-size:.82rem;border-left:2px solid rgba(227,191,111,.6);padding:2px 0 2px 10px}",
    ".wrb-trail time{color:rgba(234,241,255,.55);font-size:.74rem}",
    ".wrb-msg{margin:10px 0 0;font-size:.84rem;padding:8px 12px;border-radius:10px;background:rgba(76,214,165,.12);color:#4cd6a5}",
    ".wrb-msg.bad{background:rgba(240,120,90,.14);color:#ffb39f}",
    ".wrb-empty{font-size:.88rem;color:rgba(234,241,255,.7);padding:6px 0}",
    ".wrb-facts{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;font-size:.84rem;margin:0 0 12px}",
    ".wrb-facts dt{color:rgba(234,241,255,.6)}.wrb-facts dd{margin:0}",
    ".wrb-modal{position:fixed;inset:0;z-index:4000;background:rgba(2,8,23,.82);display:flex;flex-direction:column;padding:18px}",
    ".wrb-modal iframe{flex:1;width:100%;max-width:920px;margin:0 auto;border:0;border-radius:12px;background:#fff}",
    ".wrb-modal-bar{display:flex;justify-content:flex-end;gap:8px;max-width:920px;width:100%;margin:0 auto 10px}",
  ].join("");

  function methodSpec(id) {
    return ((board && board.methods) || []).find(function (item) { return item.id === id; }) || null;
  }

  function rowHtml(row) {
    const win = row.window || {};
    const retention = row.retention || {};
    const attempts = retention.attempts || [];
    const held = row.status === "held";
    const total = (win.window_days || board.retention_days || 1) * 86400;
    const used = held && win.seconds_left != null ? Math.max(0, Math.min(100, 100 - (win.seconds_left / total) * 100)) : 100;
    const flags = (row.flags || []).map(function (flag) {
      return "<span class=\"wrb-pill warn\" title=\"" + esc(FLAG_TEXT[flag] || flag) + "\">" + esc(FLAG_TEXT[flag] || flag) + "</span>";
    }).join(" ");
    const offer = retention.offer;
    let stateText = held ? timeLeft(win.seconds_left) : (STATUS_TEXT[row.status] || row.status);
    if (held && win.extended) stateText += " · extended";
    let html = "<div class=\"wrb-row" + (held && win.window_ended ? " ready" : "") + "\" data-row=\"" + esc(row.id) + "\">" +
      "<div class=\"wrb-line\" data-open=\"" + esc(row.id) + "\">" +
      "<div><div class=\"wrb-name\">" + esc(row.customer_name) + "</div><div class=\"wrb-id\">" + esc(row.customer_id) + " · " + esc(row.id) + "</div></div>" +
      "<div><div class=\"wrb-amount\">" + money(held || row.status === "paid_out" ? row.amount : row.requested_amount) + "</div>" +
      (row.amount < row.requested_amount && held ? "<div class=\"wrb-id\">asked " + money(row.requested_amount) + "</div>" : "") + "</div>" +
      "<div><div class=\"wrb-small\">" + esc(stateText) + "</div><div class=\"wrb-meter\"><i style=\"width:" + used.toFixed(0) + "%\"></i></div></div>" +
      "<div class=\"wrb-small\">" + esc((row.reason && row.reason.label) || "No reason given") + "</div>" +
      "<div>" + (offer && offer.status === "open" ? "<span class=\"wrb-pill ok\">Offer open</span> " : "") +
      "<span class=\"wrb-pill\">" + attempts.length + (attempts.length === 1 ? " step" : " steps") + "</span></div>" +
      "</div>";
    if (openRow === row.id) html += detailHtml(row, flags);
    return html + "</div>";
  }

  function detailHtml(row, flags) {
    const retention = row.retention || {};
    const attempts = (retention.attempts || []).slice().reverse();
    const held = row.status === "held";
    const win = row.window || {};
    const bank = row.bank || {};
    const offer = retention.offer;
    const offerOpen = offer && offer.status === "open";
    let html = "<div class=\"wrb-detail\"><div class=\"wrb-cols\"><div>" +
      "<dl class=\"wrb-facts\">" +
      "<dt>Reason</dt><dd>" + esc((row.reason && row.reason.label) || "—") +
      (row.reason && row.reason.note ? " · “" + esc(row.reason.note) + "”" : "") + "</dd>" +
      "<dt>To</dt><dd>" + esc(bank.holder || "—") + " · " + esc(bank.bank_name || "") + " · •••• " + esc(bank.account_last4 || "") + "</dd>" +
      "<dt>Filed</dt><dd>" + esc(when(row.filed_at)) + "</dd>" +
      (held ? "<dt>Transfer after</dt><dd>" + esc(when(win.release_after)) + "</dd>" : "") +
      "<dt>Wallet now</dt><dd>" + money(row.wallet_balance) + "</dd>" +
      "<dt>Seal</dt><dd>" + (row.seal_intact === false ? "<span class=\"wrb-pill warn\">Does not match</span>"
        : "<span class=\"wrb-pill ok\">Intact</span>") +
      (retention.trail_intact === false ? " <span class=\"wrb-pill warn\">Trail does not match</span>" : "") + "</dd>" +
      (flags ? "<dt>Flags</dt><dd>" + flags + "</dd>" : "") +
      (offer ? "<dt>Offer</dt><dd>" + esc(offer.label.replace(/^Offer:\s*/, "")) + " · " + esc(offer.status) +
        (offer.keep_amount && offer.method === "offer_partial" ? " · keep " + money(offer.keep_amount) : "") + "</dd>" : "") +
      "</dl>";
    if (held) {
      html += "<p class=\"wrb-h\">Retention methods</p><div class=\"wrb-methods\">" +
        (board.methods || []).map(function (method) {
          const blocked = (method.kind === "offer" && offerOpen) || (method.id === "extend_hold" && win.extended);
          return "<button type=\"button\" class=\"wrb-method" + (openMethod === method.id ? " on" : "") +
            (method.id === row.suggested_method && !blocked ? " suggested" : "") + "\" data-method=\"" + esc(method.id) +
            "\" title=\"" + esc(method.hint) + "\"" + (blocked ? " disabled" : "") + ">" + esc(method.label) + "</button>";
        }).join("") + "</div>";
      if (openMethod) html += formHtml(row, methodSpec(openMethod));
    }
    html += "<div class=\"wrb-btns\" style=\"margin-top:14px;\">" +
      "<button type=\"button\" class=\"wrb-btn ghost\" data-act=\"document\">Open the withdrawal document</button>" +
      "<a class=\"wrb-btn ghost\" style=\"text-decoration:none;\" href=\"#customers-section\" data-act=\"find\">Find in the customer list</a>";
    if (held && board.can_pay_out) {
      html += "<button type=\"button\" class=\"wrb-btn\" data-act=\"release\"" + (win.window_ended ? "" : " disabled title=\"The retention window has not ended\"") +
        ">Release " + money(row.amount) + " to the bank</button>" +
        "<button type=\"button\" class=\"wrb-btn danger\" data-act=\"decline\">Decline and return to wallet</button>";
    }
    html += "</div>";
    if (message && message.row === row.id) {
      html += "<p class=\"wrb-msg" + (message.bad ? " bad" : "") + "\">" + esc(message.text) + "</p>";
    }
    html += "</div><div><p class=\"wrb-h\">Trail</p>";
    if (!attempts.length) {
      html += "<p class=\"wrb-empty\">No retention step yet. The transfer goes ahead when the window ends.</p>";
    } else {
      html += "<ul class=\"wrb-trail\">" + attempts.map(function (entry) {
        const spec = methodSpec(entry.method);
        const label = spec ? spec.label : (entry.method === "release" ? "Released" : entry.method === "decline" ? "Declined"
          : String(entry.method || "").replace(/_/g, " "));
        return "<li><strong>" + esc(label) + "</strong> · " + esc(String(entry.outcome || "").replace(/_/g, " ")) +
          "<br>" + esc(entry.note || "") + "<br><time>" + esc(when(entry.at)) + " · " + esc(entry.actor) + "</time></li>";
      }).join("") + "</ul>";
    }
    return html + "</div></div></div>";
  }

  function formHtml(row, spec) {
    if (!spec) return "";
    let fields = "";
    if (spec.id === "outreach_message" || spec.kind === "offer") {
      fields += "<label>" + (spec.kind === "offer" ? "What the customer reads with the offer" : "Message to the customer") +
        "<textarea id=\"wrb-message\" maxlength=\"600\"></textarea></label>";
    }
    if (spec.id === "outreach_message") {
      fields += "<label>Channel<select id=\"wrb-channels\"><option value=\"both\">Email and WhatsApp</option>" +
        "<option value=\"email\">Email</option><option value=\"whatsapp\">WhatsApp</option></select></label>";
    }
    if (spec.needs === "keep_amount") {
      fields += "<label>Amount that stays in the wallet (of " + money(row.amount) + ")" +
        "<input id=\"wrb-keep\" type=\"number\" min=\"0.01\" step=\"0.01\" max=\"" + esc(row.amount) + "\"></label>";
    }
    if (spec.needs === "days") {
      fields += "<label>Extra days<select id=\"wrb-days\"><option>1</option><option>2</option><option>3</option><option>4</option></select></label>";
    }
    const noteLabel = spec.kind === "offer" || spec.id === "outreach_message" ? "Desk note (the customer does not see it)"
      : spec.id === "extend_hold" ? "Reason for the extension"
        : spec.id === "escalate" ? "Reason for the escalation" : "What was said or noted";
    fields += "<label>" + noteLabel + "<textarea id=\"wrb-note\" maxlength=\"500\"></textarea></label>";
    return "<div class=\"wrb-form\"><p class=\"wrb-small\" style=\"margin:0;\">" + esc(spec.hint) + "</p>" + fields +
      "<div class=\"wrb-btns\"><button type=\"button\" class=\"wrb-btn\" data-act=\"record\">" +
      (spec.kind === "offer" ? "Place the offer" : spec.id === "outreach_message" ? "Send" : "Record") + "</button>" +
      "<button type=\"button\" class=\"wrb-btn ghost\" data-act=\"close-method\">Cancel</button></div></div>";
  }

  function render() {
    if (!board) { mount.innerHTML = ""; return; }
    const held = (board.items || []).filter(function (row) { return row.status === "held"; });
    const flagged = filter === "held" ? board.flagged : held.length;
    const quiet = !flagged;
    let html = "<style>" + STYLE + "</style><section class=\"wrb" + (quiet ? " quiet" : "") + "\" aria-label=\"Withdrawal retention\">" +
      "<div class=\"wrb-head\" data-toggle=\"1\">" +
      "<span class=\"wrb-flag\" aria-hidden=\"true\">" + flagged + "</span>" +
      "<div><div class=\"wrb-title\">Withdrawal retention</div><div class=\"wrb-sub\">" +
      (flagged ? flagged + (flagged === 1 ? " customer has" : " customers have") + " a health-wallet withdrawal on hold. " +
        "The transfer waits " + board.retention_days + (board.retention_days === 1 ? " day" : " days") + " for customer relations."
        : "No withdrawal is on hold right now.") + "</div></div>" +
      "<div class=\"wrb-figs\"><span><b>" + money(filter === "held" ? board.held_amount : held.reduce(function (sum, row) { return sum + row.amount; }, 0)) +
      "</b>on hold</span><span><b>" + (filter === "held" ? board.ready_to_release : held.filter(function (row) { return (row.window || {}).window_ended; }).length) +
      "</b>window ended</span></div>" +
      "<button type=\"button\" class=\"wrb-toggle\" aria-expanded=\"" + (expanded ? "true" : "false") + "\" aria-label=\"" +
      (expanded ? "Fold the retention bar" : "Unfold the retention bar") + "\">" + (expanded ? "−" : "+") + "</button></div>";
    if (expanded) {
      html += "<div class=\"wrb-body\"><div class=\"wrb-tabs\">" +
        [["held", "On hold"], ["all", "All requests"]].map(function (tab) {
          return "<button type=\"button\" class=\"wrb-tab" + (filter === tab[0] ? " on" : "") + "\" data-filter=\"" + tab[0] + "\">" + tab[1] + "</button>";
        }).join("") + "</div>";
      if (!(board.items || []).length) {
        html += "<p class=\"wrb-empty\">" + (filter === "held" ? "No customer is flagged." : "No withdrawal has been filed yet.") + "</p>";
      } else {
        html += board.items.map(rowHtml).join("");
      }
      html += "</div>";
    }
    mount.innerHTML = html + "</section>";
  }

  async function load(keepMessage) {
    if (!keepMessage) message = null;
    try {
      board = await call("GET", "?status=" + encodeURIComponent(filter));
    } catch (err) {
      // A role without the retention desk simply has no bar.
      board = null;
      mount.innerHTML = "";
      return;
    }
    if (board.flagged && !sessionStorage.getItem("wrb_seen")) {
      expanded = true;
      try { sessionStorage.setItem("wrb_seen", "1"); } catch (err) { /* storage is closed */ }
    }
    render();
  }

  function rowOf(node) {
    const holder = node.closest("[data-row]");
    const id = holder ? holder.getAttribute("data-row") : "";
    return (board.items || []).find(function (row) { return row.id === id; }) || null;
  }

  function say(row, text, bad) {
    message = { row: row.id, text: text, bad: !!bad };
  }

  async function record(row) {
    const spec = methodSpec(openMethod);
    if (!spec) return;
    const read = function (id) { const node = document.getElementById(id); return node ? node.value.trim() : ""; };
    const body = { method: spec.id, note: read("wrb-note"), message: read("wrb-message") };
    if (spec.needs === "keep_amount") body.keep_amount = Number(read("wrb-keep"));
    if (spec.needs === "days") body.days = Number(read("wrb-days"));
    if (spec.id === "outreach_message") body.channels = read("wrb-channels") || "both";
    try {
      const payload = await call("POST", "/" + encodeURIComponent(row.id) + "/retention", body);
      const last = ((payload.withdrawal.retention || {}).attempts || []).slice(-1)[0] || {};
      const text = last.outcome === "not_sent"
        ? "The message was not sent" + ((last.delivery && last.delivery.error) ? ": " + last.delivery.error : ".") + " The attempt is on the trail."
        : spec.kind === "offer" ? "The offer is open. The customer sees it on their withdrawal page."
          : spec.label + " recorded.";
      say(row, text, last.outcome === "not_sent");
      openMethod = "";
      await load(true);
    } catch (err) {
      say(row, err.message, true);
      render();
    }
  }

  async function showDocument(row) {
    try {
      const payload = await call("GET", "/" + encodeURIComponent(row.id) + "/document");
      const modal = document.createElement("div");
      modal.className = "wrb-modal";
      modal.innerHTML = "<div class=\"wrb-modal-bar\"><button type=\"button\" class=\"wrb-btn ghost\" data-print=\"1\">Print</button>" +
        "<button type=\"button\" class=\"wrb-btn\" data-close=\"1\">Close</button></div><iframe title=\"Withdrawal document\"></iframe>";
      const frame = modal.querySelector("iframe");
      frame.srcdoc = payload.html || "";
      modal.querySelector("[data-close]").addEventListener("click", function () { modal.remove(); });
      modal.querySelector("[data-print]").addEventListener("click", function () {
        try { frame.contentWindow.focus(); frame.contentWindow.print(); } catch (err) { /* frame closed */ }
      });
      mount.appendChild(modal);
    } catch (err) {
      say(row, err.message, true);
      render();
    }
  }

  async function release(row) {
    const reference = window.prompt("Bank transfer reference for " + money(row.amount) + " to " + row.customer_name + ":", "");
    if (reference === null) return;
    try {
      await call("POST", "/" + encodeURIComponent(row.id) + "/release", { reference: reference });
      say(row, money(row.amount) + " released to the bank account ending " + ((row.bank || {}).account_last4 || "") + ".");
      filter = "all";
      await load(true);
    } catch (err) {
      say(row, err.message, true);
      render();
    }
  }

  async function decline(row) {
    const reason = window.prompt("Reason for declining. " + money(row.amount) + " returns to the customer's wallet:", "");
    if (reason === null) return;
    try {
      await call("POST", "/" + encodeURIComponent(row.id) + "/decline", { reason: reason });
      say(row, "Declined. " + money(row.amount) + " is back in the customer's health wallet.");
      filter = "all";
      await load(true);
    } catch (err) {
      say(row, err.message, true);
      render();
    }
  }

  mount.addEventListener("click", function (event) {
    const target = event.target;
    if (!board || target.closest(".wrb-modal")) return;
    const tab = target.closest("[data-filter]");
    if (tab) { filter = tab.getAttribute("data-filter"); openRow = ""; openMethod = ""; load(); return; }
    const method = target.closest("[data-method]");
    if (method) {
      openMethod = openMethod === method.getAttribute("data-method") ? "" : method.getAttribute("data-method");
      message = null;
      render();
      const first = mount.querySelector(".wrb-form textarea, .wrb-form input");
      if (first) first.focus();
      return;
    }
    const action = target.closest("[data-act]");
    if (action) {
      const row = rowOf(action);
      if (!row) return;
      const name = action.getAttribute("data-act");
      if (name === "record") record(row);
      else if (name === "close-method") { openMethod = ""; render(); }
      else if (name === "document") showDocument(row);
      else if (name === "release") release(row);
      else if (name === "decline") decline(row);
      else if (name === "find") {
        const search = document.getElementById("search-input");
        if (search) {
          search.value = row.customer_id;
          search.dispatchEvent(new Event("input", { bubbles: true }));
          search.dispatchEvent(new Event("keyup", { bubbles: true }));
          search.scrollIntoView({ behavior: "smooth", block: "center" });
        }
        event.preventDefault();
      }
      return;
    }
    if (target.closest(".wrb-form") || target.closest(".wrb-detail")) return;
    const line = target.closest("[data-open]");
    if (line) {
      const id = line.getAttribute("data-open");
      openRow = openRow === id ? "" : id;
      openMethod = "";
      message = null;
      render();
      return;
    }
    if (target.closest("[data-toggle]")) {
      expanded = !expanded;
      render();
    }
  });

  load();
  timer = setInterval(function () {
    // Refresh the countdowns while nobody is typing into a method form.
    if (!openMethod && !mount.querySelector(".wrb-modal")) load(true);
  }, 60000);
  window.addEventListener("beforeunload", function () { if (timer) clearInterval(timer); });
})();
