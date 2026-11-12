"use strict";

const assert = require("assert");
const otp = require("../web_portal/static/professional-inquiry-chat.js");

const serverMessages = [
  { role: "bot", text: "I sent a 6-digit code to i***@example.com. Type it in this chat." },
];
const chat = { cursor: "identity", messages: serverMessages.slice() };
const shown = otp.inquiryOtpMessages(chat, "123456");

assert.strictEqual(shown.messages.length, 2);
assert.ok(shown.messages[1].text.includes("123456"));
assert.strictEqual(serverMessages[0].text.includes("123456"), false);
assert.strictEqual(chat.messages.length, 1);
assert.strictEqual(JSON.stringify(chat.messages).includes("123456"), false);

const failed = otp.inquiryOtpAfterFailedVerify(shown, "That code was not accepted.");
assert.ok(failed.messages.some(function (item) { return item.text.includes("123456"); }));
assert.ok(failed.messages.some(function (item) { return item.text.includes("not accepted"); }));
assert.strictEqual(shown.messages.length, 2);

const again = otp.inquiryOtpAfterFailedVerify(failed, "That code was not accepted.");
assert.strictEqual(again.messages.filter(function (item) {
  return item.text.includes("123456");
}).length, 1);
