/*
 * Health-wallet withdrawal chat.
 *
 * The page asks; the server decides. Every answer goes to
 * /api/customer/wallet-withdrawals and the reply is the whole request, so a
 * reload continues where the conversation stopped.
 */
(function () {
  "use strict";

  const API = "/api/customer/wallet-withdrawals";
  const STEP_TITLES = {
    details: "Your details",
    amount: "Amount",
    reason: "Reason",
    bank: "Bank account",
    id_document: "Identity document",
    photo: "Photo",
    bank_document: "Bank document",
    signature: "Signature",
    review: "Review and file",
  };
  const STATUS_TEXT = {
    held: "Held for transfer",
    reversed: "Returned to your wallet",
    declined: "Declined, returned to your wallet",
    paid_out: "Paid to your bank",
    discarded: "Discarded",
  };
  const MAX_UPLOAD_BYTES = 6 * 1024 * 1024;
  const RESIZE_ABOVE_BYTES = 2.5 * 1024 * 1024;

  const welcome = document.getElementById("welcome-screen");
  const welcomeError = document.getElementById("welcome-error");
  const welcomeSub = document.getElementById("welcome-sub");
  const startBtn = document.getElementById("start-btn");
  const screen = document.getElementById("chat-screen");
  const scroll = document.getElementById("chat-scroll");
  const dock = document.getElementById("chat-dock");
  const strip = document.getElementById("process-strip");
  const docModal = document.getElementById("doc-modal");
  const docFrame = document.getElementById("doc-frame");

  let view = null;
  let editing = null;
  let busy = false;
  let countdownTimer = null;
  let acceptedNext = "";

  function token() {
    let session = {};
    try { session = JSON.parse(localStorage.getItem("session") || "{}") || {}; } catch (err) { session = {}; }
    const found = session.token || localStorage.getItem("phins_token") || sessionStorage.getItem("phins_token") || "";
    const text = String(found || "").trim();
    return text && text !== "undefined" && text !== "null" ? text : "";
  }

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function money(value) {
    const number = Number(value || 0);
    return "$" + number.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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
    let response;
    try {
      response = await fetch(API + path, options);
    } catch (err) {
      throw { status: 0, message: "The connection dropped. Nothing was changed; please try again." };
    }
    let payload = {};
    try { payload = await response.json(); } catch (err) { payload = {}; }
    if (!response.ok) {
      throw { status: response.status, code: payload.code, message: payload.error || "That did not go through." };
    }
    return payload;
  }

  // ---- screens -----------------------------------------------------------

  function showWelcomeError(text) {
    welcomeError.hidden = false;
    welcomeError.textContent = text;
  }

  function dockHtml(html) {
    dock.innerHTML = "<div class=\"dock-inner\">" + html + "<div class=\"dock-error\" id=\"dock-error\" hidden></div></div>";
  }

  function dockError(text) {
    const node = document.getElementById("dock-error");
    if (!node) return;
    node.hidden = !text;
    node.textContent = text || "";
  }

  function setBusy(flag) {
    busy = flag;
    dock.querySelectorAll("button, input, select").forEach(function (node) { node.disabled = flag; });
  }

  async function act(method, path, body) {
    if (busy) return null;
    dockError("");
    setBusy(true);
    try {
      const payload = await call(method, path, body);
      if (payload.withdrawal) {
        view = payload.withdrawal;
        editing = null;
        render();
      }
      return payload;
    } catch (err) {
      setBusy(false);
      if (err.status === 401) { window.location.href = "/login.html"; return null; }
      dockError(err.message);
      return null;
    }
  }

  function renderStrip() {
    if (!view) { strip.hidden = true; return; }
    const steps = view.steps || Object.keys(STEP_TITLES);
    const draft = view.status === "draft";
    const current = draft ? (editing || (view.step && view.step.id)) : null;
    strip.hidden = false;
    strip.innerHTML = steps.map(function (step) {
      const done = !draft || (view.answers && view.answers[step]);
      let cls = "process-chip";
      if (done) cls += " done";
      if (step === current) cls += " now";
      const canEdit = draft && done && step !== "review";
      const tag = canEdit ? "button" : "span";
      const attrs = canEdit ? " type=\"button\" data-edit=\"" + esc(step) + "\" title=\"Change this answer\"" : "";
      return "<" + tag + " class=\"" + cls + "\"" + attrs + ">" + esc(STEP_TITLES[step] || step) + "</" + tag + ">";
    }).join("");
    strip.querySelectorAll("[data-edit]").forEach(function (node) {
      node.style.cursor = "pointer";
      node.style.font = "inherit";
      node.style.fontSize = "0.78rem";
      node.addEventListener("click", function () {
        if (busy) return;
        editing = node.getAttribute("data-edit");
        render();
      });
    });
  }

  function renderMessages() {
    const rows = (view.messages || []).map(function (message) {
      const who = message.from === "user" ? "user" : "bot";
      const avatar = who === "bot" ? "<div class=\"msg-avatar\"><img src=\"/phins-logo.svg\" alt=\"\"></div>" : "";
      return "<div class=\"msg-row " + who + "\">" + avatar + "<div class=\"msg-bubble\">" + esc(message.text) + "</div></div>";
    });
    scroll.innerHTML = rows.join("");
    requestAnimationFrame(function () { scroll.scrollTop = scroll.scrollHeight; });
  }

  function render() {
    if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null; }
    busy = false;
    welcome.hidden = true;
    screen.hidden = false;
    renderStrip();
    renderMessages();
    if (view.status === "draft") {
      const step = editing ? localStep(editing) : view.step;
      renderStep(step);
    } else {
      renderStatus();
    }
  }

  function localStep(id) {
    const details = view.details || {};
    const inputs = {
      details: { type: "confirm_details", details: details },
      amount: { type: "amount", min: 1, max: view.wallet_balance, currency: "USD" },
      reason: null,
      bank: { type: "bank", holder: details.name || "" },
      id_document: { type: "upload", kind: "id_document", accept: "image/jpeg,image/png,image/webp,application/pdf" },
      photo: { type: "photo_crop" },
      bank_document: { type: "upload", kind: "bank_document", accept: "image/jpeg,image/png,image/webp,application/pdf" },
      signature: { type: "signature", signer_name: (view.signature && view.signature.signer_name) || details.name || "" },
    };
    if (id === "reason") {
      return { id: id, input: { type: "choice", options: REASON_OPTIONS, note: true } };
    }
    return { id: id, input: inputs[id] };
  }

  let REASON_OPTIONS = [];

  function backLink() {
    return editing ? "<button type=\"button\" class=\"link-quiet\" id=\"edit-back\">Keep my earlier answer</button><span class=\"spacer\"></span>" : "<span class=\"spacer\"></span>";
  }

  function wireBack() {
    const node = document.getElementById("edit-back");
    if (node) node.addEventListener("click", function () { editing = null; render(); });
  }

  function renderStep(step) {
    if (!step || !step.input) { dock.innerHTML = ""; return; }
    const input = step.input;
    if (input.type === "choice" && input.options && input.options.length) REASON_OPTIONS = input.options;
    if (input.type === "confirm_details") return renderDetails(input);
    if (input.type === "amount") return renderAmount(input);
    if (input.type === "choice") return renderReason(input);
    if (input.type === "bank") return renderBank(input);
    if (input.type === "upload") return renderUpload(step.id, input);
    if (input.type === "photo_crop") return renderCrop();
    if (input.type === "signature") return renderSignature(input);
    return renderReview(input);
  }

  function renderDetails(input) {
    const d = input.details || {};
    const identity = d.identity_on_file
      ? esc(d.national_id_masked || "on file") + (d.nationality ? " · " + esc(d.nationality) : "")
      : "Not on file yet. The identity document you upload is reviewed by staff.";
    dockHtml(
      "<dl class=\"wd-details\">" +
      "<dt>Name</dt><dd>" + esc(d.name || "—") + "</dd>" +
      "<dt>Email</dt><dd>" + esc(d.email || "—") + "</dd>" +
      "<dt>Phone</dt><dd>" + esc(d.phone || "—") + "</dd>" +
      "<dt>Address</dt><dd>" + esc(d.address || "—") + "</dd>" +
      "<dt>Identity</dt><dd>" + identity + "</dd>" +
      "</dl>" +
      "<div class=\"wd-actions\">" + backLink() +
      "<a class=\"link-quiet\" href=\"/dashboard.html#profile\">Something changed</a>" +
      "<button type=\"button\" class=\"chip chip-go\" id=\"details-ok\">Yes, these are right</button></div>"
    );
    wireBack();
    document.getElementById("details-ok").addEventListener("click", function () {
      act("POST", "/" + view.id + "/answer", { step: "details", value: { confirm: true } });
    });
  }

  function renderAmount(input) {
    const max = Number(input.max || 0);
    const current = view.amount > 0 ? view.amount : "";
    dockHtml(
      "<div class=\"dock-label\">Amount to withdraw · up to " + money(max) + "</div>" +
      "<div class=\"dock-row\">" +
      "<input class=\"dock-input\" id=\"amount-input\" type=\"number\" inputmode=\"decimal\" min=\"" + esc(input.min || 1) +
      "\" max=\"" + esc(max) + "\" step=\"0.01\" placeholder=\"0.00\" value=\"" + esc(current) + "\">" +
      "<button type=\"button\" class=\"send-btn\" id=\"amount-send\" aria-label=\"Send amount\">➤</button></div>" +
      "<div class=\"chips-wrap\" style=\"margin-top:10px;\">" +
      [0.25, 0.5, 1].map(function (share) {
        const value = Math.floor(max * share * 100) / 100;
        return "<button type=\"button\" class=\"chip\" data-amount=\"" + value + "\">" +
          (share === 1 ? "All of it" : Math.round(share * 100) + "%") + " · " + money(value) + "</button>";
      }).join("") + "</div>" +
      "<div class=\"wd-actions\">" + backLink() + "</div>"
    );
    wireBack();
    const field = document.getElementById("amount-input");
    const send = function () {
      const amount = Number(field.value);
      if (!(amount > 0)) { dockError("Type the amount you want to withdraw."); return; }
      if (amount > max + 1e-9) { dockError("Your health wallet holds " + money(max) + ". Choose an amount up to that."); return; }
      act("POST", "/" + view.id + "/answer", { step: "amount", value: { amount: amount } });
    };
    dock.querySelectorAll("[data-amount]").forEach(function (node) {
      node.addEventListener("click", function () { field.value = node.getAttribute("data-amount"); field.focus(); });
    });
    document.getElementById("amount-send").addEventListener("click", send);
    field.addEventListener("keydown", function (event) { if (event.key === "Enter") send(); });
    field.focus({ preventScroll: true });
  }

  function renderReason(input) {
    const chosen = (view.reason && view.reason.code) || "";
    dockHtml(
      "<div class=\"chips-wrap\">" + (input.options || []).map(function (option) {
        return "<button type=\"button\" class=\"chip" + (option.value === chosen ? " selected" : "") + "\" data-reason=\"" +
          esc(option.value) + "\">" + esc(option.label) + "</button>";
      }).join("") + "</div>" +
      "<div class=\"dock-row\" style=\"margin-top:10px;\">" +
      "<input class=\"dock-input\" id=\"reason-note\" type=\"text\" maxlength=\"300\" placeholder=\"Anything you want us to know (optional)\" value=\"" +
      esc((view.reason && view.reason.note) || "") + "\"></div>" +
      "<div class=\"wd-actions\">" + backLink() +
      "<button type=\"button\" class=\"chip chip-go\" id=\"reason-send\">Continue</button></div>"
    );
    wireBack();
    let code = chosen;
    dock.querySelectorAll("[data-reason]").forEach(function (node) {
      node.addEventListener("click", function () {
        code = node.getAttribute("data-reason");
        dock.querySelectorAll("[data-reason]").forEach(function (other) { other.classList.toggle("selected", other === node); });
        dockError("");
      });
    });
    document.getElementById("reason-send").addEventListener("click", function () {
      if (!code) { dockError("Choose the reason that fits best."); return; }
      act("POST", "/" + view.id + "/answer", {
        step: "reason", value: { code: code, note: document.getElementById("reason-note").value },
      });
    });
  }

  function renderBank(input) {
    const bank = view.bank || {};
    const field = function (id, label, value, extra) {
      return "<label" + (extra && extra.wide ? " class=\"wide\"" : "") + ">" + esc(label) +
        "<input id=\"" + id + "\" type=\"text\" value=\"" + esc(value || "") + "\" autocomplete=\"" +
        ((extra && extra.autocomplete) || "off") + "\" placeholder=\"" + esc((extra && extra.placeholder) || "") + "\"></label>";
    };
    dockHtml(
      "<div class=\"wd-fields two\">" +
      field("bank-holder", "Account holder", bank.holder || input.holder, { autocomplete: "name" }) +
      field("bank-name", "Bank", bank.bank_name, { placeholder: "Bank name" }) +
      field("bank-account", "IBAN or account number", "", {
        wide: true,
        placeholder: bank.account_last4 ? "Type it again to change •••• " + bank.account_last4 : "IL62 0108 0000 0009 9999 999",
      }) +
      field("bank-branch", "Branch (for an account number)", bank.branch, { placeholder: "Branch number" }) +
      field("bank-country", "Country of the bank", bank.country || (view.details && view.details.nationality) || "", { placeholder: "Israel" }) +
      field("bank-swift", "SWIFT / BIC (optional)", bank.swift, { placeholder: "8 or 11 characters" }) +
      "</div>" +
      "<p class=\"wd-note\">The account number is stored encrypted. Staff and this page see only its last four digits.</p>" +
      "<div class=\"wd-actions\">" + backLink() +
      "<button type=\"button\" class=\"chip chip-go\" id=\"bank-send\">Use this account</button></div>"
    );
    wireBack();
    const valueOf = function (id) { return document.getElementById(id).value.trim(); };
    document.getElementById("bank-send").addEventListener("click", function () {
      if (!valueOf("bank-account")) { dockError("Type the IBAN or the account number."); return; }
      act("POST", "/" + view.id + "/answer", {
        step: "bank",
        value: {
          holder: valueOf("bank-holder"), bank_name: valueOf("bank-name"), account: valueOf("bank-account"),
          branch: valueOf("bank-branch"), country: valueOf("bank-country"), swift: valueOf("bank-swift"),
        },
      });
    });
  }

  // ---- uploads -----------------------------------------------------------

  function readDataUrl(blob) {
    return new Promise(function (resolve, reject) {
      const reader = new FileReader();
      reader.onload = function () { resolve(String(reader.result || "")); };
      reader.onerror = function () { reject(new Error("read failed")); };
      reader.readAsDataURL(blob);
    });
  }

  function loadImage(url) {
    return new Promise(function (resolve, reject) {
      const image = new Image();
      image.onload = function () { resolve(image); };
      image.onerror = function () { reject(new Error("image failed")); };
      image.src = url;
    });
  }

  // A phone photo can be larger than one request allows. The picture is
  // reduced here; what the server receives is what it seals.
  async function prepareFile(file) {
    const isImage = /^image\//.test(file.type || "");
    if (!isImage || file.size <= RESIZE_ABOVE_BYTES) {
      if (file.size > MAX_UPLOAD_BYTES) throw new Error("That file is larger than 6 MB. Please upload a smaller one.");
      return { mime: file.type || "", data: (await readDataUrl(file)).split(",")[1] || "" };
    }
    const image = await loadImage(await readDataUrl(file));
    const scale = Math.min(1, 2600 / Math.max(image.naturalWidth, image.naturalHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
    return { mime: "image/jpeg", data: canvas.toDataURL("image/jpeg", 0.9).split(",")[1] || "" };
  }

  function renderUpload(stepId, input) {
    const kind = input.kind;
    const titles = {
      id_document: "Upload your identity document",
      bank_document: "Upload your bank document",
      photo_source: "Upload a picture that shows your face",
    };
    const have = (view.documents || {})[kind];
    dockHtml(
      "<label class=\"wd-drop\" id=\"drop\">" +
      "<strong>" + esc(titles[kind] || "Upload a file") + "</strong>" +
      "<span>" + (kind === "photo_source" ? "JPEG, PNG, or WebP" : "JPEG, PNG, WebP, or PDF") + " · up to 6 MB · tap to choose or drop it here</span>" +
      (have ? "<span>On file: " + esc(have.file_name || "uploaded") + ". Choosing another file replaces it.</span>" : "") +
      "<input type=\"file\" id=\"file-input\" accept=\"" + esc(input.accept || "") + "\">" +
      "</label>" +
      "<div class=\"wd-actions\">" + backLink() + "</div>"
    );
    wireBack();
    const drop = document.getElementById("drop");
    const fileInput = document.getElementById("file-input");
    const send = async function (file) {
      if (!file || busy) return;
      dockError("");
      let prepared;
      try {
        prepared = await prepareFile(file);
      } catch (err) {
        dockError(err.message || "That file could not be read.");
        return;
      }
      drop.querySelector("strong").textContent = "Sealing " + (file.name || "your file") + "…";
      const result = await act("POST", "/" + view.id + "/upload", { kind: kind, mime_type: prepared.mime, data: prepared.data });
      if (!result) drop.querySelector("strong").textContent = titles[kind] || "Upload a file";
    };
    fileInput.addEventListener("change", function () { send(fileInput.files && fileInput.files[0]); });
    ["dragenter", "dragover"].forEach(function (name) {
      drop.addEventListener(name, function (event) { event.preventDefault(); drop.classList.add("over"); });
    });
    ["dragleave", "drop"].forEach(function (name) {
      drop.addEventListener(name, function (event) { event.preventDefault(); drop.classList.remove("over"); });
    });
    drop.addEventListener("drop", function (event) {
      send(event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0]);
    });
  }

  // ---- photo crop --------------------------------------------------------

  async function renderCrop() {
    dockHtml("<p class=\"wd-note\">Reading your document…</p><div class=\"wd-actions\">" + backLink() + "</div>");
    wireBack();
    let source;
    try {
      source = await call("GET", "/" + view.id + "/photo-source");
    } catch (err) {
      if (err.code === "photo_source_missing" || err.code === "photo_source_not_image") {
        renderUpload("photo", { type: "upload", kind: "photo_source", accept: "image/jpeg,image/png,image/webp" });
        dockError("Upload a picture of a document that shows your face.");
        return;
      }
      dockError(err.message);
      return;
    }
    let image;
    try {
      image = await loadImage(source.preview);
    } catch (err) {
      dockError("The document preview could not be shown.");
      return;
    }
    const aspect = Number(source.aspect) || 0.8;
    const found = source.method === "skin_region";
    dockHtml(
      "<div class=\"dock-label\">" + (found
        ? "I found your photo on the document. Drag the gold frame or change its size if it is off."
        : "I could not find the photo myself. Drag the gold frame over your face.") + "</div>" +
      "<div class=\"wd-crop\"><div><canvas id=\"crop-stage\"></canvas>" +
      "<input type=\"range\" id=\"crop-size\" min=\"8\" max=\"100\" step=\"1\" aria-label=\"Frame size\"></div>" +
      "<div class=\"wd-crop-side\"><canvas id=\"crop-preview\" width=\"240\" height=\"300\"></canvas>" +
      "<span>Your photo on the withdrawal document</span></div></div>" +
      "<div class=\"wd-actions\">" + backLink() +
      "<button type=\"button\" class=\"link-quiet\" id=\"crop-other\">Use another picture</button>" +
      "<button type=\"button\" class=\"chip chip-go\" id=\"crop-ok\">That is my photo</button></div>"
    );
    wireBack();
    const stage = document.getElementById("crop-stage");
    const preview = document.getElementById("crop-preview");
    const slider = document.getElementById("crop-size");
    const ctx = stage.getContext("2d");
    const pctx = preview.getContext("2d");
    const cssWidth = Math.max(220, Math.min(stage.parentElement.clientWidth || 480, 560));
    const ratio = image.naturalHeight / image.naturalWidth;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    stage.style.width = cssWidth + "px";
    stage.style.height = Math.round(cssWidth * ratio) + "px";
    stage.width = Math.round(cssWidth * dpr);
    stage.height = Math.round(cssWidth * ratio * dpr);
    const W = stage.width;
    const H = stage.height;

    // The frame is kept in image fractions, the way the server reads it.
    let box = source.box.slice();
    let moved = false;
    const heightFor = function (width) { return width * image.naturalWidth / (aspect * image.naturalHeight); };
    const maxWidth = Math.min(1, aspect * image.naturalHeight / image.naturalWidth);

    function clamp() {
      box[2] = Math.max(0.06, Math.min(box[2], maxWidth));
      box[3] = Math.min(1, heightFor(box[2]));
      box[0] = Math.max(0, Math.min(box[0], 1 - box[2]));
      box[1] = Math.max(0, Math.min(box[1], 1 - box[3]));
    }

    function draw() {
      ctx.drawImage(image, 0, 0, W, H);
      const x = box[0] * W, y = box[1] * H, w = box[2] * W, h = box[3] * H;
      ctx.fillStyle = "rgba(6, 13, 31, 0.6)";
      ctx.fillRect(0, 0, W, y);
      ctx.fillRect(0, y + h, W, H - y - h);
      ctx.fillRect(0, y, x, h);
      ctx.fillRect(x + w, y, W - x - w, h);
      ctx.strokeStyle = "#e3bf6f";
      ctx.lineWidth = 3 * dpr;
      ctx.strokeRect(x, y, w, h);
      pctx.fillStyle = "#0a1531";
      pctx.fillRect(0, 0, preview.width, preview.height);
      pctx.drawImage(
        image,
        box[0] * image.naturalWidth, box[1] * image.naturalHeight,
        box[2] * image.naturalWidth, box[3] * image.naturalHeight,
        0, 0, preview.width, preview.height
      );
    }

    slider.value = Math.round(box[2] / maxWidth * 100);
    draw();

    let drag = null;
    const point = function (event) {
      const rect = stage.getBoundingClientRect();
      return { x: (event.clientX - rect.left) / rect.width, y: (event.clientY - rect.top) / rect.height };
    };
    stage.addEventListener("pointerdown", function (event) {
      const p = point(event);
      const inside = p.x >= box[0] && p.x <= box[0] + box[2] && p.y >= box[1] && p.y <= box[1] + box[3];
      if (!inside) {
        box[0] = p.x - box[2] / 2;
        box[1] = p.y - box[3] / 2;
        moved = true;
        clamp();
        draw();
      }
      drag = { dx: p.x - box[0], dy: p.y - box[1] };
      stage.classList.add("dragging");
      try { stage.setPointerCapture(event.pointerId); } catch (err) { /* not capturable */ }
      event.preventDefault();
    });
    stage.addEventListener("pointermove", function (event) {
      if (!drag) return;
      const p = point(event);
      box[0] = p.x - drag.dx;
      box[1] = p.y - drag.dy;
      moved = true;
      clamp();
      draw();
    });
    const stop = function () { drag = null; stage.classList.remove("dragging"); };
    stage.addEventListener("pointerup", stop);
    stage.addEventListener("pointercancel", stop);
    slider.addEventListener("input", function () {
      const centerX = box[0] + box[2] / 2;
      const centerY = box[1] + box[3] / 2;
      box[2] = Number(slider.value) / 100 * maxWidth;
      box[3] = heightFor(box[2]);
      box[0] = centerX - box[2] / 2;
      box[1] = centerY - box[3] / 2;
      moved = true;
      clamp();
      draw();
    });
    document.getElementById("crop-ok").addEventListener("click", function () {
      act("POST", "/" + view.id + "/photo", { box: moved ? box.map(function (v) { return Math.round(v * 10000) / 10000; }) : "proposal" });
    });
    document.getElementById("crop-other").addEventListener("click", function () {
      renderUpload("photo", { type: "upload", kind: "photo_source", accept: "image/jpeg,image/png,image/webp" });
    });
  }

  // ---- signature ---------------------------------------------------------

  function renderSignature(input) {
    dockHtml(
      "<div class=\"dock-label\">Electronic signature</div>" +
      "<div class=\"dock-row\" style=\"margin-bottom:10px;\">" +
      "<input class=\"dock-input\" id=\"signer-name\" type=\"text\" autocomplete=\"name\" placeholder=\"Full legal name\" value=\"" +
      esc(input.signer_name || "") + "\"></div>" +
      "<div class=\"sig-pad-wrap\"><canvas class=\"sig-pad\" id=\"sig-pad\" width=\"520\" height=\"140\" aria-label=\"Draw your signature\"></canvas>" +
      "<div class=\"sig-pad-actions\"><button type=\"button\" class=\"link-btn\" id=\"sig-clear\">Clear signature</button>" +
      "<span class=\"dock-hint\" id=\"sig-hint\">Draw your signature above</span></div></div>" +
      "<div class=\"wd-actions\">" + backLink() +
      "<button type=\"button\" class=\"chip chip-go\" id=\"sign-send\">Sign the withdrawal</button></div>"
    );
    wireBack();
    const canvas = document.getElementById("sig-pad");
    const hint = document.getElementById("sig-hint");
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    let drawing = false;
    let last = null;
    let fitted = false;

    // Opaque white paper on a device-pixel bitmap: the server counts dark
    // ink, so the guideline is pale and the stroke is navy.
    function fit() {
      const rect = canvas.getBoundingClientRect();
      const cssW = rect.width;
      const cssH = rect.height || 140;
      if (cssW < 2 || cssH < 2) return false;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.max(1, Math.round(cssW * dpr));
      canvas.height = Math.max(1, Math.round(cssH * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, cssW, cssH);
      ctx.strokeStyle = "#d7dce6";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(16, cssH * 0.78);
      ctx.lineTo(Math.max(17, cssW - 16), cssH * 0.78);
      ctx.stroke();
      fitted = true;
      drawing = false;
      last = null;
      return true;
    }
    if (!fit()) requestAnimationFrame(function () { if (!drawing) fit(); });

    function pos(event) {
      const rect = canvas.getBoundingClientRect();
      return { x: event.clientX - rect.left, y: event.clientY - rect.top };
    }
    function inkCount() {
      if (!fitted) return 0;
      let pixels;
      try { pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data; } catch (err) { return 0; }
      let count = 0;
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i + 3] > 40 && (pixels[i] + pixels[i + 1] + pixels[i + 2]) < 520 &&
            Math.min(pixels[i], pixels[i + 1], pixels[i + 2]) < 180) {
          count += 1;
          if (count >= 8) return count;
        }
      }
      return count;
    }
    canvas.addEventListener("pointerdown", function (event) {
      if (!fitted && !fit()) return;
      event.preventDefault();
      drawing = true;
      last = pos(event);
      try { canvas.setPointerCapture(event.pointerId); } catch (err) { /* not capturable */ }
    });
    canvas.addEventListener("pointermove", function (event) {
      if (!drawing || !last) return;
      event.preventDefault();
      const p = pos(event);
      ctx.strokeStyle = "#0d2a5c";
      ctx.lineWidth = 2.4;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.beginPath();
      ctx.moveTo(last.x, last.y);
      ctx.lineTo(p.x, p.y);
      ctx.stroke();
      last = p;
      if (inkCount() >= 8) hint.textContent = "Signature captured";
    });
    const end = function () { drawing = false; last = null; };
    canvas.addEventListener("pointerup", end);
    canvas.addEventListener("pointercancel", end);
    canvas.addEventListener("pointerleave", end);
    document.getElementById("sig-clear").addEventListener("click", function () {
      fit();
      hint.textContent = "Draw your signature above";
    });
    document.getElementById("sign-send").addEventListener("click", function () {
      const name = document.getElementById("signer-name").value.trim();
      if (name.length < 2) { dockError("Type your full legal name."); return; }
      if (inkCount() < 8) { dockError("Draw your signature in the white panel."); return; }
      act("POST", "/" + view.id + "/sign", { signer_name: name, image_data: canvas.toDataURL("image/png") });
    });
  }

  // ---- review and status -------------------------------------------------

  function bankLine(bank) {
    if (!bank || !bank.account_last4) return "—";
    const kind = bank.account_kind === "iban" ? "IBAN" : "Account";
    return esc(bank.holder) + " · " + esc(bank.bank_name) + (bank.branch ? " · branch " + esc(bank.branch) : "") +
      " · " + kind + " •••• " + esc(bank.account_last4);
  }

  function renderReview(input) {
    const documents = view.documents || {};
    dockHtml(
      "<div class=\"wd-review\">" +
      (input.portrait ? "<img src=\"" + esc(input.portrait) + "\" alt=\"Your photo from the document\">" : "<span></span>") +
      "<dl class=\"wd-details\" style=\"margin:0;\">" +
      "<dt>Amount</dt><dd><strong>" + money(view.amount) + "</strong> of " + money(view.wallet_balance) + " in your wallet</dd>" +
      "<dt>Reason</dt><dd>" + esc((view.reason && view.reason.label) || "—") + "</dd>" +
      "<dt>To</dt><dd>" + bankLine(view.bank) + "</dd>" +
      "<dt>Identity file</dt><dd>" + esc((documents.id_document && documents.id_document.file_name) || "—") + "</dd>" +
      "<dt>Bank file</dt><dd>" + esc((documents.bank_document && documents.bank_document.file_name) || "—") + "</dd>" +
      "<dt>Signed as</dt><dd>" + esc((view.signature && view.signature.signer_name) || "—") + "</dd>" +
      "</dl></div>" +
      "<p class=\"wd-note\">Tap a step above to change an answer. A change asks you to sign again.</p>" +
      "<div class=\"wd-actions\">" +
      "<button type=\"button\" class=\"link-quiet\" id=\"discard\">Discard this request</button><span class=\"spacer\"></span>" +
      "<button type=\"button\" class=\"chip chip-go\" id=\"file-send\">File my withdrawal of " + money(view.amount) + "</button></div>"
    );
    document.getElementById("file-send").addEventListener("click", function () {
      act("POST", "/" + view.id + "/file", { confirm: true });
    });
    document.getElementById("discard").addEventListener("click", function () {
      if (!window.confirm("Discard this request? Nothing has left your wallet.")) return;
      act("POST", "/" + view.id + "/cancel", { reason: "Discarded before filing" });
    });
  }

  function countdownText(seconds) {
    if (seconds <= 0) return "The hold has ended. The transfer is with the payments desk.";
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const parts = [];
    if (days) parts.push(days + (days === 1 ? " day" : " days"));
    if (hours || days) parts.push(hours + (hours === 1 ? " hour" : " hours"));
    if (!days) parts.push(minutes + (minutes === 1 ? " minute" : " minutes"));
    return "Transfer in " + parts.join(" ") + ". You can cancel until then.";
  }

  function renderStatus() {
    const status = view.status;
    const offer = view.offer;
    const window_ = view.window || {};
    const closed = view.closed || {};
    let html = "<div class=\"wd-status\">" +
      "<span class=\"wd-pill " + esc(status) + "\">" + esc(STATUS_TEXT[status] || status) + "</span>" +
      "<div class=\"big\">" + money(status === "held" || status === "paid_out" ? view.amount : view.requested_amount) + "</div>";
    if (status === "discarded") {
      html += "<p class=\"wd-note\">This request was discarded before filing. Nothing left your wallet.</p>";
    } else {
      html += "<dl class=\"wd-details\">" +
        "<dt>Request</dt><dd>" + esc(view.id) + "</dd>" +
        "<dt>To</dt><dd>" + bankLine(view.bank) + "</dd>" +
        "<dt>Wallet now</dt><dd>" + money(view.wallet_balance) + "</dd>" +
        (view.nft_token_id ? "<dt>Wallet NFT</dt><dd>" + esc(view.nft_token_id) + "</dd>" : "") +
        "</dl>";
    }
    if (status === "held") {
      html += "<p class=\"wd-note\" id=\"countdown\"></p>";
      if (view.amount < view.requested_amount) {
        html += "<p class=\"wd-note\">You first asked for " + money(view.requested_amount) + "; " +
          money(view.requested_amount - view.amount) + " went back to your wallet.</p>";
      }
    } else if (closed.reason) {
      html += "<p class=\"wd-note\">" + esc(closed.reason) + "</p>";
    }
    if (status === "held" && offer) {
      html += "<div class=\"wd-offer\"><h3>" + esc(offer.label.replace(/^Offer:\s*/, "An option from customer relations: ")) + "</h3>" +
        "<p>" + esc(offer.message || "") + "</p>" +
        (offer.keep_amount ? "<p>" + money(offer.keep_amount) + " would return to your wallet and " +
          money(view.amount - offer.keep_amount) + " would still be transferred.</p>" : "") +
        "<div class=\"wd-actions\" style=\"margin-top:0;\">" +
        "<button type=\"button\" class=\"link-quiet\" id=\"offer-no\">No thanks, continue the withdrawal</button><span class=\"spacer\"></span>" +
        "<button type=\"button\" class=\"chip chip-go\" id=\"offer-yes\">Accept</button></div></div>";
    }
    html += "<div class=\"wd-actions\">";
    if (status === "held") html += "<button type=\"button\" class=\"link-quiet\" id=\"cancel\">Cancel and return it to my wallet</button>";
    html += "<span class=\"spacer\"></span>";
    if (status !== "discarded") html += "<button type=\"button\" class=\"chip\" id=\"open-doc\">Open the withdrawal document</button>";
    if (status === "reversed" && acceptedNext) {
      html += "<a class=\"chip\" style=\"text-decoration:none;\" href=\"" + esc(acceptedNext) + "\">" +
        (acceptedNext.indexOf("savings") > -1 ? "Open my savings" : "Open my billing") + "</a>";
    }
    if (status !== "held") html += "<a class=\"chip chip-go\" style=\"text-decoration:none;\" href=\"/dashboard.html#health-wallet\">Back to my wallet</a>";
    html += "</div><div class=\"dock-error\" id=\"dock-error\" hidden></div></div>";
    dock.innerHTML = html;

    const countdown = document.getElementById("countdown");
    if (countdown && window_.release_after) {
      const releaseAt = new Date(window_.release_after).getTime();
      const tick = function () { countdown.textContent = countdownText(Math.round((releaseAt - Date.now()) / 1000)); };
      tick();
      countdownTimer = setInterval(tick, 30000);
    }
    const on = function (id, handler) {
      const node = document.getElementById(id);
      if (node) node.addEventListener("click", handler);
    };
    on("cancel", function () {
      if (!window.confirm("Cancel this withdrawal? " + money(view.amount) + " returns to your health wallet now.")) return;
      act("POST", "/" + view.id + "/cancel", { reason: "Cancelled by the customer" });
    });
    on("offer-yes", function () {
      acceptedNext = offer.next || "";
      act("POST", "/" + view.id + "/offer", { offer_id: offer.offer_id, decision: "accept" });
    });
    on("offer-no", function () {
      act("POST", "/" + view.id + "/offer", { offer_id: offer.offer_id, decision: "decline" });
    });
    on("open-doc", openDocument);
  }

  async function openDocument() {
    dockError("");
    try {
      const payload = await call("GET", "/" + view.id + "/document");
      docFrame.srcdoc = payload.html || "";
      docModal.hidden = false;
    } catch (err) {
      dockError(err.message);
    }
  }

  document.getElementById("doc-close").addEventListener("click", function () {
    docModal.hidden = true;
    docFrame.srcdoc = "";
  });
  document.getElementById("doc-print").addEventListener("click", function () {
    try { docFrame.contentWindow.focus(); docFrame.contentWindow.print(); } catch (err) { window.print(); }
  });

  // ---- start -------------------------------------------------------------

  async function boot() {
    let listing;
    try {
      listing = await call("GET", "");
    } catch (err) {
      if (err.status === 401) { window.location.href = "/login.html"; return; }
      showWelcomeError(err.status === 403
        ? "A withdrawal is opened by the customer from their own wallet."
        : err.message);
      return;
    }
    const wanted = new URLSearchParams(window.location.search).get("id");
    const open = listing.open;
    if (wanted || (open && open.status === "held")) {
      try {
        const payload = await call("GET", "/" + encodeURIComponent(wanted || open.id));
        view = payload.withdrawal;
        render();
        return;
      } catch (err) {
        showWelcomeError(err.message);
      }
    }
    if (open && open.status === "draft") {
      startBtn.textContent = "Continue my withdrawal";
      welcomeSub.textContent = "You started a withdrawal earlier. Your answers are saved; nothing has left your wallet yet.";
    } else if (listing.retention_days) {
      welcomeSub.textContent += " After you file, the amount is held for " + listing.retention_days +
        (listing.retention_days === 1 ? " day" : " days") + " before the transfer, and you can cancel during that time.";
    }
    startBtn.disabled = false;
    startBtn.addEventListener("click", async function () {
      startBtn.disabled = true;
      welcomeError.hidden = true;
      try {
        const payload = await call("POST", "", {});
        view = payload.withdrawal;
        render();
      } catch (err) {
        startBtn.disabled = false;
        if (err.status === 401) { window.location.href = "/login.html"; return; }
        showWelcomeError(err.message);
      }
    });
  }

  boot();
})();
