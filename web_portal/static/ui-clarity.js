(() => {
  const LEADING_EMOJI_RE = /^\s*(?:[\u{1F1E6}-\u{1F1FF}\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2300}-\u{23FF}\u{FE0F}\u{200D}])+\s*/u;
  const TARGET_SELECTOR = [
    "nav a",
    ".phins-nav a",
    "button",
    ".btn",
    ".compact-tab",
    ".mini-tab",
    ".pill-tab",
    "[role='tab']",
  ].join(", ");

  const FLOATING_BAR_ID = "phins-vqa-bar";
  const FLOATING_STYLE_ID = "phins-vqa-inline-style";
  const VQA_INPUT_ID = "phins-vqa-input";
  const VQA_STATUS_ID = "phins-vqa-status";
  const VQA_ACTIONS_ID = "phins-vqa-actions";
  const VQA_TOGGLE_ID = "phins-vqa-toggle";
  const VQA_PANEL_ID = "phins-vqa-panel";
  const VQA_VOICE_BTN_ID = "phins-vqa-voice-btn";
  const VQA_PENDING_ACTION_KEY = "phins_vqa_pending_admin_action";
  const VQA_PENDING_ACTION_TTL_MS = 2 * 60 * 1000;

  let floatingRecognition = null;
  let floatingListening = false;

  function cleanLeadingEmoji(element) {
    if (!element) {
      return;
    }

    if (element.closest && element.closest(`#${FLOATING_BAR_ID}`)) {
      return;
    }

    for (const child of element.childNodes) {
      if (child.nodeType !== Node.TEXT_NODE) {
        if (child.nodeType === Node.ELEMENT_NODE && child.tagName === "SPAN") {
          cleanLeadingEmoji(child);
        }
        continue;
      }

      const original = child.textContent || "";
      if (!original.trim()) {
        continue;
      }

      const cleaned = original.replace(LEADING_EMOJI_RE, "");
      if (cleaned !== original && cleaned.trim().length > 0) {
        child.textContent = cleaned.replace(/^\s+/, "");
      }
      break;
    }
  }

  function runCleanup(root = document) {
    const nodes = root.querySelectorAll ? root.querySelectorAll(TARGET_SELECTOR) : [];
    nodes.forEach(cleanLeadingEmoji);
  }

  function getSessionRole() {
    try {
      const raw = localStorage.getItem("session");
      if (!raw) return "";
      const parsed = JSON.parse(raw);
      return String(parsed?.role || "").toLowerCase();
    } catch {
      return "";
    }
  }

  function isAdminRole(role) {
    return ["admin", "underwriter", "claims_adjuster", "accountant", "actuary"].includes(role);
  }

  function isStaffPath(pathname) {
    const p = String(pathname || "").toLowerCase();
    return [
      "/admin",
      "/underwriter-dashboard",
      "/claims-adjuster-dashboard",
      "/billing",
      "/accountant-dashboard",
      "/actuary-dashboard",
      "/admin-supplier-dashboard",
      "/admin-media",
      "/admin-foundations",
      "/risk-dashboard",
      "/risk-reports-dashboard",
      "/video-agents",
      "/pitch-dashboard",
    ].some((prefix) => p.includes(prefix));
  }

  function detectContext() {
    const role = getSessionRole();
    const path = (window.location.pathname || "").toLowerCase();
    const hasAdminAssistant =
      typeof window.adminAssistantProcessQuery === "function" ||
      typeof window.adminAssistantQuickAction === "function";
    const hasCustomerAssistant =
      typeof window.processAIQuery === "function" ||
      typeof window.quickAIAction === "function";

    if (hasAdminAssistant || isStaffPath(path) || isAdminRole(role)) {
      return "admin";
    }
    if (hasCustomerAssistant || path.includes("/dashboard")) {
      return "customer";
    }
    return "generic";
  }

  function setFloatingStatus(message, kind = "info") {
    const statusNode = document.getElementById(VQA_STATUS_ID);
    if (!statusNode) return;
    statusNode.textContent = message;
    statusNode.dataset.kind = kind;
  }

  function getAdminAssistantBranding() {
    const isAdminContext = detectContext() === "admin";
    if (isAdminContext) {
      return {
        toggleLabel: "Admin AI Mic",
        title: "PHINS admin AI Assistant",
        placeholder: "Voice or type admin command...",
      };
    }
    return {
      toggleLabel: "Voice Quick Actions",
      title: "Voice Quick Actions",
      placeholder: "Type action...",
    };
  }

  function getSessionToken() {
    return localStorage.getItem("phins_token") || "";
  }

  function setPendingAdminAction(actionId) {
    try {
      const payload = { actionId, createdAt: Date.now() };
      sessionStorage.setItem(VQA_PENDING_ACTION_KEY, JSON.stringify(payload));
    } catch {
      // no-op
    }
  }

  function consumePendingAdminAction() {
    try {
      const raw = sessionStorage.getItem(VQA_PENDING_ACTION_KEY);
      if (!raw) return null;
      sessionStorage.removeItem(VQA_PENDING_ACTION_KEY);
      const parsed = JSON.parse(raw);
      if (!parsed?.actionId || !parsed?.createdAt) return null;
      if (Date.now() - Number(parsed.createdAt) > VQA_PENDING_ACTION_TTL_MS) return null;
      return parsed.actionId;
    } catch {
      return null;
    }
  }

  function getFloatingActionsForContext(context) {
    const role = getSessionRole();
    const actions = {
      admin: [
        { id: "admin_overview", label: "Admin", query: "refresh overview", requiresAdmin: true, url: "/admin.html" },
        { id: "admin_underwriting", label: "Underwriter", query: "open underwriter dashboard", requiresAdmin: true, url: "/underwriter-dashboard.html" },
        { id: "admin_claims", label: "Claims", query: "open claims adjuster dashboard", requiresAdmin: true, url: "/claims-adjuster-dashboard.html" },
        { id: "admin_billing", label: "Billing", query: "open billing dashboard", requiresAdmin: true, url: "/billing.html" },
        { id: "admin_accounting", label: "Accountant", query: "open accountant dashboard", requiresAdmin: true, url: "/accountant-dashboard.html" },
        { id: "admin_actuary", label: "Actuary", query: "open actuary dashboard", requiresAdmin: true, url: "/actuary-dashboard.html" },
        { id: "admin_portfolio_simulation", label: "Actuary Sim", query: "run portfolio simulation", requiresAdmin: true, url: "/actuary-dashboard.html" },
        { id: "admin_investments", label: "Investments", query: "open savings portfolio dashboard", requiresAdmin: true, url: "/savings-portfolio.html" },
        { id: "admin_ai_bi", label: "AI + BI", query: "run ai bi insights", requiresAdmin: true, url: "/admin.html" },
        { id: "admin_media", label: "Media", query: "open admin media dashboard", requiresAdmin: true, url: "/admin-media.html" },
        { id: "admin_foundations", label: "Foundations", query: "open admin foundations dashboard", requiresAdmin: true, url: "/admin-foundations.html" },
        { id: "admin_video_agents", label: "Video Agents", query: "open video agents dashboard", requiresAdmin: true, url: "/video-agents.html" },
        { id: "admin_pitch", label: "Pitch", query: "open pitch dashboard", requiresAdmin: true, url: "/pitch-dashboard.html" },
        { id: "admin_risk", label: "Risk", query: "open risk dashboard", requiresAdmin: true, url: "/risk-dashboard.html" },
        { id: "admin_reports", label: "Reports", query: "open risk reports dashboard", requiresAdmin: true, url: "/risk-reports-dashboard.html" },
        { id: "admin_logout", label: "Logout", query: "logout", requiresAdmin: true, url: "/" },
      ],
      customer: [
        { id: "cust_policies", label: "Policies", query: "show me my policies", url: "/dashboard.html" },
        { id: "cust_billing", label: "Billing", query: "show me all my billings", url: "/dashboard.html" },
        { id: "cust_claims", label: "Claims", query: "i want to file a claim", url: "/dashboard.html" },
        { id: "cust_wallet", label: "Wallet", query: "check my wallet balance", url: "/dashboard.html" },
      ],
      generic: [
        { id: "go_dashboard", label: "Customer", query: "show me my policies", url: "/dashboard.html" },
        { id: "go_billing", label: "Billing", query: "show me all my billings", url: "/billing.html" },
        { id: "go_risk", label: "Risk", query: "open risk dashboard", url: "/risk-dashboard.html" },
        { id: "go_admin", label: "Admin", query: "refresh overview", requiresAdmin: true, url: "/admin.html" },
      ],
    };

    const selected = actions[context] || actions.generic;
    return selected.filter((action) => {
      if (!action.requiresAdmin) return true;
      return isAdminRole(role);
    });
  }

  function ensureFloatingStyles() {
    if (document.getElementById(FLOATING_STYLE_ID)) {
      return;
    }
    const style = document.createElement("style");
    style.id = FLOATING_STYLE_ID;
    style.textContent = `
      #${FLOATING_BAR_ID} {
        position: fixed;
        right: 16px;
        bottom: 16px;
        z-index: 2140;
        font-family: Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      }
      #${FLOATING_BAR_ID} #${VQA_TOGGLE_ID} {
        border: none;
        border-radius: 999px;
        background: linear-gradient(135deg, #4a148c 0%, #7b1fa2 100%);
        color: #fff;
        padding: 12px 16px;
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.02em;
        box-shadow: 0 10px 28px rgba(74, 20, 140, 0.34);
        cursor: pointer;
      }
      #${FLOATING_BAR_ID}.open #${VQA_TOGGLE_ID} {
        display: none;
      }
      #${VQA_PANEL_ID} {
        width: min(330px, calc(100vw - 24px));
        border-radius: 14px;
        background: linear-gradient(135deg, #4a148c 0%, #7b1fa2 55%, #9c27b0 100%);
        box-shadow: 0 14px 36px rgba(74, 20, 140, 0.36);
        color: #fff;
        padding: 12px;
        display: none;
      }
      #${FLOATING_BAR_ID}.open #${VQA_PANEL_ID} {
        display: block;
      }
      .phins-vqa-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 10px;
        margin-bottom: 10px;
      }
      .phins-vqa-title {
        font-size: 0.82rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        opacity: 0.95;
      }
      .phins-vqa-min {
        border: 1px solid rgba(255,255,255,0.35);
        background: rgba(255,255,255,0.16);
        color: #fff;
        border-radius: 8px;
        padding: 4px 8px;
        font-size: 0.8rem;
        cursor: pointer;
      }
      .phins-vqa-row {
        display: grid;
        grid-template-columns: 1fr auto auto;
        gap: 6px;
        margin-bottom: 8px;
      }
      #${VQA_INPUT_ID} {
        border: 1px solid rgba(255,255,255,0.35);
        border-radius: 10px;
        padding: 8px 10px;
        font-size: 0.84rem;
        outline: none;
      }
      .phins-vqa-ask,
      #${VQA_VOICE_BTN_ID} {
        border: none;
        border-radius: 10px;
        padding: 8px 10px;
        font-size: 0.78rem;
        font-weight: 700;
        cursor: pointer;
      }
      .phins-vqa-ask {
        background: linear-gradient(135deg, #e1bee7 0%, #ce93d8 100%);
        color: #4a148c;
      }
      #${VQA_VOICE_BTN_ID} {
        background: rgba(255,255,255,0.2);
        color: #fff;
        border: 1px solid rgba(255,255,255,0.35);
      }
      #${VQA_VOICE_BTN_ID}[data-listening="true"] {
        background: linear-gradient(135deg, #f44336 0%, #d32f2f 100%);
        border-color: transparent;
      }
      #${VQA_STATUS_ID} {
        font-size: 0.75rem;
        margin-bottom: 8px;
        color: rgba(255,255,255,0.92);
      }
      #${VQA_STATUS_ID}[data-kind="error"] { color: #ffebee; }
      #${VQA_STATUS_ID}[data-kind="warning"] { color: #fff8e1; }
      .phins-vqa-actions {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
      }
      .phins-vqa-action-btn {
        border: 1px solid rgba(255,255,255,0.32);
        background: rgba(255,255,255,0.14);
        color: #fff;
        border-radius: 14px;
        padding: 6px 10px;
        font-size: 0.74rem;
        font-weight: 700;
        cursor: pointer;
      }
      .phins-vqa-action-btn:hover {
        background: rgba(255,255,255,0.26);
      }
      @media (max-width: 768px) {
        #${FLOATING_BAR_ID} {
          right: 10px;
          bottom: 10px;
        }
        #${VQA_PANEL_ID} {
          width: min(310px, calc(100vw - 16px));
        }
      }
    `;
    document.head.appendChild(style);
  }

  function renderFloatingActions() {
    const actionsNode = document.getElementById(VQA_ACTIONS_ID);
    if (!actionsNode) return;
    const context = detectContext();
    if (actionsNode.dataset.context === context) {
      return;
    }
    actionsNode.dataset.context = context;
    const actions = getFloatingActionsForContext(context);
    actionsNode.innerHTML = "";

    actions.forEach((action) => {
      const btn = document.createElement("button");
      btn.className = "phins-vqa-action-btn";
      btn.type = "button";
      btn.textContent = action.label;
      btn.addEventListener("click", () => runFloatingAction(action));
      actionsNode.appendChild(btn);
    });
  }

  function callIfFunction(fn) {
    if (typeof fn !== "function") {
      return;
    }
    try {
      const result = fn();
      if (result && typeof result.then === "function") {
        result.catch(() => {});
      }
    } catch {
      // no-op
    }
  }

  function routeQueryToPageAssistant(query) {
    const normalized = String(query || "").toLowerCase();

    if (normalized.includes("run portfolio simulation") && typeof window.runSimulation === "function") {
      callIfFunction(window.runSimulation);
      setFloatingStatus("Running actuary portfolio simulation.", "info");
      return true;
    }
    if ((normalized.includes("automation") || normalized.includes("actuary automation")) && typeof window.calculateAutomation === "function") {
      callIfFunction(window.calculateAutomation);
      setFloatingStatus("Running actuary automation metrics.", "info");
      return true;
    }

    if ((normalized === "logout" || normalized.includes("sign out") || normalized.includes("log out")) && typeof window.logout === "function") {
      const proceed = window.confirm("Logout now?");
      if (!proceed) {
        setFloatingStatus("Logout cancelled.", "warning");
        return true;
      }
      callIfFunction(window.logout);
      return true;
    }

    const adminInput = document.getElementById("admin-ai-query-input");
    if (adminInput && typeof window.adminAssistantProcessQuery === "function") {
      adminInput.value = query;
      callIfFunction(window.adminAssistantProcessQuery);
      setFloatingStatus("Dispatched to admin assistant.", "info");
      return true;
    }

    const customerInput = document.getElementById("ai-query-input");
    if (customerInput && typeof window.processAIQuery === "function") {
      customerInput.value = query;
      callIfFunction(window.processAIQuery);
      setFloatingStatus("Dispatched to customer assistant.", "info");
      return true;
    }

    return false;
  }

  function fallbackNavigateForQuery(query) {
    const q = String(query || "").toLowerCase();
    if (!q) return false;
    const role = getSessionRole();
    const adminOnlyCommand =
      q.includes("admin") ||
      q.includes("underwriter") ||
      q.includes("claims adjuster") ||
      q.includes("accountant") ||
      q.includes("actuary") ||
      q.includes("reconcile") ||
      q.includes("ai bi") ||
      q.includes("risk reports") ||
      q.includes("video agents") ||
      q.includes("pitch dashboard") ||
      q.includes("portfolio simulation");

    if (adminOnlyCommand && !isAdminRole(role)) {
      setFloatingStatus("Admin role required for this command.", "warning");
      return true;
    }

    if (q.includes("logout") || q.includes("sign out") || q.includes("log out")) {
      const proceed = window.confirm("Logout now?");
      if (!proceed) return true;
      try {
        sessionStorage.clear();
        localStorage.removeItem("phins_token");
      } catch {
        // no-op
      }
      window.location.href = "/";
      return true;
    }

    if (q.includes("run portfolio simulation") || q.includes("portfolio simulation")) {
      setPendingAdminAction("run_actuary_portfolio_simulation");
      window.location.href = "/actuary-dashboard.html";
      return true;
    }

    if (q.includes("open actuary") || q.includes("actuary dashboard")) {
      window.location.href = "/actuary-dashboard.html";
      return true;
    }
    if (q.includes("underwriter dashboard")) {
      window.location.href = "/underwriter-dashboard.html";
      return true;
    }
    if (q.includes("claims adjuster") || q.includes("claims dashboard")) {
      window.location.href = "/claims-adjuster-dashboard.html";
      return true;
    }
    if (q.includes("accountant dashboard")) {
      window.location.href = "/accountant-dashboard.html";
      return true;
    }
    if (q.includes("supplier dashboard")) {
      window.location.href = "/admin-supplier-dashboard.html";
      return true;
    }
    if (q.includes("media dashboard")) {
      window.location.href = "/admin-media.html";
      return true;
    }
    if (q.includes("foundations dashboard")) {
      window.location.href = "/admin-foundations.html";
      return true;
    }
    if (q.includes("risk reports")) {
      window.location.href = "/risk-reports-dashboard.html";
      return true;
    }
    if (q.includes("savings portfolio") || q.includes("investments dashboard")) {
      window.location.href = "/savings-portfolio.html";
      return true;
    }
    if (q.includes("video agents")) {
      window.location.href = "/video-agents.html";
      return true;
    }
    if (q.includes("pitch dashboard")) {
      window.location.href = "/pitch-dashboard.html";
      return true;
    }

    if (q.includes("admin") || q.includes("underwriting") || q.includes("reconcile") || q.includes("ai bi")) {
      window.location.href = "/admin.html";
      return true;
    }
    if (q.includes("billing")) {
      window.location.href = "/billing.html";
      return true;
    }
    if (q.includes("risk")) {
      window.location.href = "/risk-dashboard.html";
      return true;
    }
    if (q.includes("claim") || q.includes("policy") || q.includes("wallet") || q.includes("customer")) {
      window.location.href = "/dashboard.html";
      return true;
    }
    return false;
  }

  function dispatchFloatingQuery(rawQuery) {
    const query = String(rawQuery || "").trim();
    if (!query) {
      setFloatingStatus("Enter a command first.", "warning");
      return;
    }

    if (routeQueryToPageAssistant(query)) {
      return;
    }

    if (fallbackNavigateForQuery(query)) {
      setFloatingStatus("Opening relevant dashboard.", "info");
      return;
    }

    setFloatingStatus("No matching action on this page yet.", "warning");
  }

  function runFloatingAction(action) {
    if (!action) return;
    const role = getSessionRole();
    if (action.requiresAdmin && !isAdminRole(role)) {
      setFloatingStatus("Admin role required for this quick action.", "warning");
      return;
    }

    if (routeQueryToPageAssistant(action.query)) {
      return;
    }

    if (action.id === "admin_portfolio_simulation") {
      if (typeof window.runSimulation === "function") {
        setFloatingStatus("Running actuary portfolio simulation.", "info");
        callIfFunction(window.runSimulation);
        return;
      }
      setPendingAdminAction("run_actuary_portfolio_simulation");
    }

    if (action.id === "admin_logout") {
      const proceed = window.confirm("Logout now?");
      if (!proceed) {
        setFloatingStatus("Logout cancelled.", "warning");
        return;
      }
      if (typeof window.logout === "function") {
        callIfFunction(window.logout);
        return;
      }
      try {
        sessionStorage.clear();
        localStorage.removeItem("phins_token");
      } catch {
        // no-op
      }
      window.location.href = "/";
      return;
    }

    if (action.url && window.location.pathname !== action.url) {
      setFloatingStatus("Opening relevant dashboard for this action.", "info");
      window.location.href = action.url;
      return;
    }

    dispatchFloatingQuery(action.query);
  }

  function ensureFloatingVoiceRecognition() {
    if (floatingRecognition) {
      return floatingRecognition;
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      return null;
    }

    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    recognition.onstart = () => {
      floatingListening = true;
      const voiceBtn = document.getElementById(VQA_VOICE_BTN_ID);
      if (voiceBtn) {
        voiceBtn.dataset.listening = "true";
        voiceBtn.textContent = "⏹";
      }
      setFloatingStatus("Listening for voice command...", "info");
    };

    recognition.onresult = (event) => {
      let transcript = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        transcript += event.results[i][0].transcript;
      }
      const cleaned = transcript.trim();
      if (!cleaned) return;

      const input = document.getElementById(VQA_INPUT_ID);
      if (input) input.value = cleaned;
      setFloatingStatus(`Heard: "${cleaned}"`, "info");

      if (event.results[event.results.length - 1].isFinal) {
        dispatchFloatingQuery(cleaned);
      }
    };

    recognition.onerror = (event) => {
      floatingListening = false;
      const voiceBtn = document.getElementById(VQA_VOICE_BTN_ID);
      if (voiceBtn) {
        voiceBtn.dataset.listening = "false";
        voiceBtn.textContent = "🎤";
      }
      setFloatingStatus(`Voice error: ${event.error}`, "error");
    };

    recognition.onend = () => {
      floatingListening = false;
      const voiceBtn = document.getElementById(VQA_VOICE_BTN_ID);
      if (voiceBtn) {
        voiceBtn.dataset.listening = "false";
        voiceBtn.textContent = "🎤";
      }
    };

    floatingRecognition = recognition;
    return recognition;
  }

  function startFloatingVoiceInput() {
    const recognition = ensureFloatingVoiceRecognition();
    if (!recognition) {
      if (typeof window.startAdminAssistantVoiceInput === "function") {
        callIfFunction(window.startAdminAssistantVoiceInput);
        setFloatingStatus("Using admin page voice assistant.", "info");
        return;
      }
      if (typeof window.startVoiceInput === "function") {
        callIfFunction(window.startVoiceInput);
        setFloatingStatus("Using customer page voice assistant.", "info");
        return;
      }
      setFloatingStatus("Voice input is not supported in this browser.", "warning");
      return;
    }

    if (floatingListening) {
      stopFloatingVoiceInput();
      return;
    }

    try {
      recognition.start();
    } catch {
      setFloatingStatus("Could not start voice recognition.", "warning");
    }
  }

  function stopFloatingVoiceInput() {
    if (!floatingRecognition) return;
    try {
      floatingRecognition.stop();
    } catch {
      // no-op
    }
    floatingListening = false;
  }

  function ensureFloatingBar() {
    if (document.getElementById(FLOATING_BAR_ID)) {
      renderFloatingActions();
      return;
    }

    ensureFloatingStyles();

    const branding = getAdminAssistantBranding();
    const container = document.createElement("div");
    container.id = FLOATING_BAR_ID;
    container.className = "phins-vqa";
    container.innerHTML = `
      <button type="button" id="${VQA_TOGGLE_ID}" aria-label="Open voice quick actions">🎤 ${branding.toggleLabel}</button>
      <div id="${VQA_PANEL_ID}">
        <div class="phins-vqa-header">
          <div class="phins-vqa-title">${branding.title}</div>
          <button type="button" class="phins-vqa-min" id="phins-vqa-minimize" aria-label="Minimize voice quick actions">−</button>
        </div>
        <div class="phins-vqa-row">
          <input id="${VQA_INPUT_ID}" type="text" placeholder="${branding.placeholder}" />
          <button type="button" class="phins-vqa-ask" id="phins-vqa-ask-btn">Ask</button>
          <button type="button" id="${VQA_VOICE_BTN_ID}" data-listening="false">🎤</button>
        </div>
        <div id="${VQA_STATUS_ID}" data-kind="info">${detectContext() === "admin" ? "PHINS admin AI Assistant ready." : "Ready for quick actions."}</div>
        <div id="${VQA_ACTIONS_ID}" class="phins-vqa-actions"></div>
      </div>
    `;
    document.body.appendChild(container);

    const toggle = document.getElementById(VQA_TOGGLE_ID);
    const minimize = document.getElementById("phins-vqa-minimize");
    const askBtn = document.getElementById("phins-vqa-ask-btn");
    const voiceBtn = document.getElementById(VQA_VOICE_BTN_ID);
    const input = document.getElementById(VQA_INPUT_ID);

    const openBar = () => container.classList.add("open");
    const closeBar = () => container.classList.remove("open");
    toggle?.addEventListener("click", openBar);
    minimize?.addEventListener("click", closeBar);
    askBtn?.addEventListener("click", () => dispatchFloatingQuery(input?.value || ""));
    voiceBtn?.addEventListener("click", startFloatingVoiceInput);
    input?.addEventListener("keypress", (event) => {
      if (event.key === "Enter") {
        dispatchFloatingQuery(input?.value || "");
      }
    });

    renderFloatingActions();
  }

  function runPendingAdminActionIfAny() {
    const actionId = consumePendingAdminAction();
    if (!actionId) return;

    if (actionId === "run_actuary_portfolio_simulation" && typeof window.runSimulation === "function") {
      setFloatingStatus("Executing pending actuary portfolio simulation.", "info");
      callIfFunction(window.runSimulation);
      return;
    }

    setFloatingStatus("Pending action could not run on this page.", "warning");
  }

  function start() {
    document.body.classList.add("ux-compact-dashboard");
    runCleanup(document);
    ensureFloatingBar();
    runPendingAdminActionIfAny();

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        const targetElement =
          mutation.target?.nodeType === Node.TEXT_NODE
            ? mutation.target.parentElement
            : mutation.target;
        if (targetElement && targetElement.closest && targetElement.closest(`#${FLOATING_BAR_ID}`)) {
          continue;
        }
        for (const node of mutation.addedNodes) {
          if (node.nodeType !== Node.ELEMENT_NODE) {
            continue;
          }
          if (node.closest && node.closest(`#${FLOATING_BAR_ID}`)) {
            continue;
          }
          if (node.matches && node.matches(TARGET_SELECTOR)) {
            cleanLeadingEmoji(node);
          }
          runCleanup(node);
        }
      }
      renderFloatingActions();
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
