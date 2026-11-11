(function () {
  const params = new URLSearchParams(window.location.search);
  let token = params.get("t") || "";
  const welcome = document.getElementById("welcome-screen");
  const screen = document.getElementById("chat-screen");
  const scroll = document.getElementById("chat-scroll");
  const dock = document.getElementById("chat-dock");
  const strip = document.getElementById("process-strip");
  const welcomeProcess = document.getElementById("welcome-process");
  const welcomeError = document.getElementById("welcome-error");
  const classic = document.getElementById("classic-link");
  let state = null;

  if (token && classic) {
    classic.href = "/professional-inquiry.html?t=" + encodeURIComponent(token);
  }

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function showError(text) {
    welcomeError.hidden = false;
    welcomeError.textContent = text;
  }

  function renderProcess(process, cursor) {
    const steps = process || [];
    welcomeProcess.innerHTML = steps.map(function (step) {
      const mark = step.optional ? " (optional)" : "";
      return "<li><strong>" + esc(step.title) + mark + ".</strong> " + esc(step.detail) + "</li>";
    }).join("");
    strip.hidden = false;
    const order = steps.map(function (step) { return step.id; });
    const here = order.indexOf(cursor);
    strip.innerHTML = steps.map(function (step, index) {
      let cls = "process-chip";
      if (cursor === "filed" || (here > -1 && index < here)) cls += " done";
      if (step.id === cursor) cls += " now";
      return "<span class=\"" + cls + "\">" + esc(step.title) + (step.optional ? " · optional" : "") + "</span>";
    }).join("");
  }

  function renderMessages(messages) {
    scroll.innerHTML = (messages || []).map(function (message) {
      const who = message.role === "user" ? "user" : "bot";
      return "<div class=\"chat-bubble " + who + "\"><p>" + esc(message.text) + "</p></div>";
    }).join("");
    scroll.scrollTop = scroll.scrollHeight;
  }

  function field(id, label, value, type) {
    return "<label>" + esc(label) +
      "<input id=\"" + id + "\" type=\"" + (type || "text") + "\" value=\"" + esc(value || "") + "\"></label>";
  }

  function renderDock(chat) {
    dock.innerHTML = "";
    if (!chat || !chat.editable || !chat.step) {
      dock.innerHTML = "<p class=\"inquiry-note\">This application is filed. Staff review the same request on Supplier Management.</p>";
      return;
    }
    const step = chat.step;
    const input = step.input || {};
    const wrap = document.createElement("div");
    wrap.className = "inquiry-fields";
    if (input.type === "person") {
      const prefill = input.prefill || {};
      wrap.innerHTML = field("p-name", "Name", prefill.name) +
        field("p-phone", "Phone", prefill.phone, "tel") +
        field("p-address", "Address", prefill.address) +
        field("p-city", "City", prefill.city) +
        field("p-country", "Country", prefill.country);
      wrap.appendChild(button("Confirm these details", function () {
        send({
          personal: {
            name: valueOf("p-name"),
            phone: valueOf("p-phone"),
            address: valueOf("p-address"),
            city: valueOf("p-city"),
            country: valueOf("p-country"),
          },
        });
      }));
    } else if (input.type === "identity") {
      const note = document.createElement("p");
      note.className = "inquiry-note";
      if (input.can_confirm) {
        note.textContent = "On file: " + (input.nationality || "") + " " + (input.national_id_masked || "") +
          ". Confirming does not copy the number onto this application.";
        wrap.appendChild(note);
        wrap.appendChild(button("This identity is mine", function () { send("confirm"); }));
      } else {
        note.textContent = "A code goes to the email on your customer record before a new ID is recorded. The number is not kept on this application.";
        wrap.appendChild(note);
        wrap.appendChild(button("Email me a code", function () { requestCode(); }, true));
        wrap.insertAdjacentHTML("beforeend", field("otp-code", "Email code", ""));
        wrap.appendChild(button("Verify code", function () { verifyCode(); }, true));
        wrap.insertAdjacentHTML("beforeend", field("id-nation", "Nationality", "") + field("id-number", "Personal ID", "", "password"));
        wrap.appendChild(button("Record my identity", function () {
          send({ nationality: valueOf("id-nation"), national_id: valueOf("id-number") });
          const box = document.getElementById("id-number");
          if (box) box.value = "";
        }));
        if (input.can_skip) {
          wrap.appendChild(button("Skip identity", function () { send("skip"); }, true));
        }
      }
    } else if (input.type === "company") {
      const prefill = input.prefill || {};
      const options = (input.supplier_types || []).map(function (kind) {
        const selected = kind === prefill.supplier_type ? " selected" : "";
        return "<option value=\"" + esc(kind) + "\"" + selected + ">" + esc(kind) + "</option>";
      }).join("");
      wrap.innerHTML = "<p class=\"inquiry-note\">Add a company only if you are applying with one.</p>" +
        field("c-name", "Company or practice", prefill.company_name) +
        "<label>Type<select id=\"c-type\">" + options + "</select></label>" +
        field("c-reg", "Registration number", prefill.registration_number) +
        field("c-city", "City", prefill.city) +
        field("c-country", "Country", prefill.country) +
        field("c-phone", "Phone", prefill.phone, "tel");
      const actions = document.createElement("div");
      actions.className = "inquiry-actions";
      actions.appendChild(button("Apply in my own name", function () { send("no"); }, true));
      actions.appendChild(button("Add this company", function () {
        send({
          has_company: true,
          company: {
            company_name: valueOf("c-name"),
            supplier_type: valueOf("c-type"),
            registration_number: valueOf("c-reg"),
            city: valueOf("c-city"),
            country: valueOf("c-country"),
            phone: valueOf("c-phone"),
          },
        });
      }));
      wrap.appendChild(actions);
    } else if (input.type === "media") {
      wrap.innerHTML = "<p class=\"inquiry-note\">Optional. A document, a voice note, or a short video. Each file is sealed before you continue.</p>" +
        "<label>Document<input id=\"file-document\" type=\"file\" accept=\".pdf,.txt,.png,.jpg,.jpeg,image/*\"></label>" +
        "<label>Voice<input id=\"file-voice\" type=\"file\" accept=\"audio/*,.webm,.mp3,.wav\"></label>" +
        "<label>Video<input id=\"file-video\" type=\"file\" accept=\"video/*,.webm,.mp4\"></label>";
      const record = button("Record a voice note", function () { recordVoice(); }, true);
      wrap.appendChild(record);
      const files = document.createElement("div");
      files.className = "media-list";
      files.innerHTML = (chat.media || []).map(function (item) {
        return "<span>" + esc(item.kind) + " · " + esc(item.name) + " · " + esc(String(item.sha256 || "").slice(0, 12)) + "</span>";
      }).join("");
      wrap.appendChild(files);
      const actions = document.createElement("div");
      actions.className = "inquiry-actions";
      actions.appendChild(button("Skip", function () { send("skip"); }, true));
      actions.appendChild(button("Continue", function () { send("done"); }));
      wrap.appendChild(actions);
      wrap.querySelector("#file-document").addEventListener("change", function (event) {
        uploadFile(event.target.files[0], "document");
      });
      wrap.querySelector("#file-voice").addEventListener("change", function (event) {
        uploadFile(event.target.files[0], "voice");
      });
      wrap.querySelector("#file-video").addEventListener("change", function (event) {
        uploadFile(event.target.files[0], "video");
      });
    } else {
      wrap.appendChild(button("Submit this application", function () { send("submit"); }));
    }
    dock.appendChild(wrap);
  }

  function valueOf(id) {
    const el = document.getElementById(id);
    return el ? el.value : "";
  }

  function button(label, onClick, quiet) {
    const el = document.createElement("button");
    el.type = "button";
    el.className = quiet ? "btn-ghost" : "btn-gold";
    el.textContent = label;
    el.addEventListener("click", onClick);
    return el;
  }

  function applyState(body) {
    state = body;
    const chat = (body && body.chat) || {};
    renderProcess(chat.process || body.process || [], chat.cursor);
    renderMessages(chat.messages || []);
    renderDock(chat);
  }

  function dropTokenFromAddress() {
    const clean = new URL(window.location.href);
    clean.searchParams.delete("t");
    clean.searchParams.delete("token");
    const next = clean.pathname + (clean.search ? clean.search : "") + clean.hash;
    history.replaceState({}, "", next);
    token = "";
    if (classic) classic.href = "/professional-inquiry.html";
  }

  async function openSession() {
    if (!token) return true;
    const response = await fetch("/api/professional-inquiry/session", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: token }),
    });
    const body = await response.json().catch(function () { return {}; });
    if (!response.ok) {
      showError(body.error || "This link cannot be opened.");
      document.getElementById("start-btn").disabled = true;
      return false;
    }
    dropTokenFromAddress();
    return true;
  }

  async function requestCode() {
    const response = await fetch("/api/professional-inquiry/otp/request", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const body = await response.json().catch(function () { return {}; });
    const messages = (state.chat.messages || []).slice();
    messages.push({
      role: "bot",
      text: response.ok
        ? "A code is on its way to the email on your customer record."
        : (body.error || "The code could not be sent."),
    });
    renderMessages(messages);
    if (response.ok && body.verification_id) {
      state.verification_id = body.verification_id;
    }
  }

  async function verifyCode() {
    const response = await fetch("/api/professional-inquiry/otp/verify", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        verification_id: state.verification_id || "",
        otp_code: valueOf("otp-code"),
      }),
    });
    const body = await response.json().catch(function () { return {}; });
    const messages = (state.chat.messages || []).slice();
    messages.push({
      role: "bot",
      text: response.ok ? "Code verified. You can record your identity." : (body.error || "That code was not accepted."),
    });
    renderMessages(messages);
    const box = document.getElementById("otp-code");
    if (box) box.value = "";
  }

  async function load() {
    const opened = await openSession();
    if (!opened) return;
    const response = await fetch("/api/professional-inquiry", { credentials: "same-origin" });
    const body = await response.json().catch(function () { return {}; });
    if (!response.ok) {
      showError(body.error || "This link cannot be opened.");
      document.getElementById("start-btn").disabled = true;
      return;
    }
    applyState(body);
  }

  async function send(value) {
    const cursor = state && state.chat && state.chat.cursor;
    const response = await fetch("/api/professional-inquiry/chat", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ step: cursor, value: value }),
    });
    const body = await response.json().catch(function () { return {}; });
    if (!response.ok) {
      const messages = (state.chat.messages || []).slice();
      messages.push({ role: "bot", text: body.error || "That step was not accepted." });
      renderMessages(messages);
      return;
    }
    applyState(body);
  }

  function blobToB64(blob) {
    return new Promise(function (resolve, reject) {
      const reader = new FileReader();
      reader.onload = function () {
        const text = String(reader.result || "");
        resolve(text.indexOf(",") >= 0 ? text.split(",")[1] : text);
      };
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  async function uploadFile(file, kind) {
    if (!file) return;
    const data = await blobToB64(file);
    const response = await fetch("/api/professional-inquiry/media", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kind: kind,
        name: file.name,
        mime_type: file.type || "",
        data_b64: data,
      }),
    });
    const body = await response.json().catch(function () { return {}; });
    if (!response.ok) {
      const messages = (state.chat.messages || []).slice();
      messages.push({ role: "bot", text: body.error || "That file was not sealed." });
      renderMessages(messages);
      return;
    }
    applyState(body);
  }

  async function recordVoice() {
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      const messages = (state.chat.messages || []).slice();
      messages.push({ role: "bot", text: "This browser cannot record here. Choose a voice file instead." });
      renderMessages(messages);
      return;
    }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const recorder = new MediaRecorder(stream);
    const chunks = [];
    recorder.ondataavailable = function (event) {
      if (event.data && event.data.size) chunks.push(event.data);
    };
    const stopped = new Promise(function (resolve) { recorder.onstop = resolve; });
    recorder.start();
    window.setTimeout(function () { if (recorder.state !== "inactive") recorder.stop(); }, 15000);
    await stopped;
    stream.getTracks().forEach(function (track) { track.stop(); });
    const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
    const file = new File([blob], "voice-note.webm", { type: blob.type || "audio/webm" });
    await uploadFile(file, "voice");
  }

  document.getElementById("start-btn").addEventListener("click", function () {
    welcome.hidden = true;
    screen.hidden = false;
    if (state) applyState(state);
  });

  load();
})();
