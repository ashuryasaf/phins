/* Shared by the professional-inquiry chat and the classic form.
   A new email link names its request as `r` and carries the token as `t`.
   `r` is not a secret. The other page must use it at once, before the
   session exchange returns, and must not fall back to an older request
   stored in this tab. The cross-link never receives the raw token. */
(function (root, factory) {
  var api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.PhinsInquiryLink = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  var STORAGE_KEY = "phinsInquiryRequest";

  function resolveInquiryTarget(search, storedRequestId) {
    var raw = String(search || "");
    if (raw.charAt(0) === "?") raw = raw.slice(1);
    var params = new URLSearchParams(raw);
    var token = params.get("t") || "";
    var fromUrl = params.get("r") || "";
    if (token) {
      return {
        token: token,
        requestId: fromUrl,
        replaceStored: true,
        storedRequestId: fromUrl
      };
    }
    var requestId = fromUrl || storedRequestId || "";
    return {
      token: "",
      requestId: requestId,
      replaceStored: false,
      storedRequestId: storedRequestId || ""
    };
  }

  function crossHref(page, requestId) {
    if (!requestId) return "";
    return page + "?r=" + encodeURIComponent(requestId);
  }

  function applyStored(storage, resolved) {
    if (!resolved || !resolved.replaceStored || !storage) return;
    try {
      if (resolved.storedRequestId) storage.setItem(STORAGE_KEY, resolved.storedRequestId);
      else storage.removeItem(STORAGE_KEY);
    } catch (err) {}
  }

  return {
    STORAGE_KEY: STORAGE_KEY,
    resolveInquiryTarget: resolveInquiryTarget,
    crossHref: crossHref,
    applyStored: applyStored
  };
});
