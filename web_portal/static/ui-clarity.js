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

  function cleanLeadingEmoji(element) {
    if (!element) {
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

  function start() {
    document.body.classList.add("ux-compact-dashboard");
    runCleanup(document);

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === "characterData" && mutation.target.parentElement) {
          const parent = mutation.target.parentElement;
          if (parent.matches && parent.matches(TARGET_SELECTOR)) {
            cleanLeadingEmoji(parent);
          }
        }
        for (const node of mutation.addedNodes) {
          if (node.nodeType !== Node.ELEMENT_NODE) {
            continue;
          }
          if (node.matches && node.matches(TARGET_SELECTOR)) {
            cleanLeadingEmoji(node);
          }
          runCleanup(node);
        }
      }
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
