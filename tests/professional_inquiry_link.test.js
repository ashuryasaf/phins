"use strict";

const assert = require("assert");
const link = require("../web_portal/static/professional-inquiry-link.js");

function memoryStorage(initial) {
  const data = Object.assign({}, initial || {});
  return {
    getItem(key) {
      return Object.prototype.hasOwnProperty.call(data, key) ? data[key] : null;
    },
    setItem(key, value) {
      data[key] = String(value);
    },
    removeItem(key) {
      delete data[key];
    },
    snapshot() {
      return Object.assign({}, data);
    },
  };
}

const previous = "PRO-CUST-A-supplier";
const opened = "PRO-CUST-B-agent";
const token = "inq_" + "ab".repeat(16);
const storage = memoryStorage({ [link.STORAGE_KEY]: previous });

const first = link.resolveInquiryTarget("?r=" + previous, storage.getItem(link.STORAGE_KEY));
assert.strictEqual(first.token, "");
assert.strictEqual(first.requestId, previous);
assert.strictEqual(link.crossHref("/professional-inquiry.html", first.requestId),
  "/professional-inquiry.html?r=" + encodeURIComponent(previous));

const second = link.resolveInquiryTarget("?r=" + opened + "&t=" + token, previous);
link.applyStored(storage, second);
assert.strictEqual(second.requestId, opened);
assert.strictEqual(storage.getItem(link.STORAGE_KEY), opened);
const chatToForm = link.crossHref("/professional-inquiry.html", second.requestId);
const formToChat = link.crossHref("/professional-inquiry-chat.html", second.requestId);
assert.strictEqual(chatToForm, "/professional-inquiry.html?r=" + encodeURIComponent(opened));
assert.strictEqual(formToChat, "/professional-inquiry-chat.html?r=" + encodeURIComponent(opened));
assert.ok(!chatToForm.includes(token));
assert.ok(!formToChat.includes("t="));
assert.ok(!chatToForm.includes(previous));

const legacy = link.resolveInquiryTarget("?t=" + token, opened);
const cleared = memoryStorage({ [link.STORAGE_KEY]: opened });
link.applyStored(cleared, legacy);
assert.strictEqual(legacy.requestId, "");
assert.strictEqual(cleared.getItem(link.STORAGE_KEY), null);
assert.strictEqual(link.crossHref("/professional-inquiry.html", legacy.requestId), "");

const cookieOnly = link.resolveInquiryTarget("", previous);
assert.strictEqual(cookieOnly.requestId, "");
assert.notStrictEqual(cookieOnly.requestId, previous);
const remembered = link.adoptedRequestId(cookieOnly.requestId, opened);
assert.strictEqual(remembered, opened);
assert.notStrictEqual(remembered, previous);
const cookieHref = link.crossHref("/professional-inquiry.html", remembered);
assert.strictEqual(cookieHref, "/professional-inquiry.html?r=" + encodeURIComponent(opened));
assert.ok(!cookieHref.includes(token));
assert.ok(!cookieHref.includes("t="));
assert.strictEqual(link.adoptedRequestId(previous, opened), opened);

console.log("two inquiries in one tab stay on the link that just opened");
