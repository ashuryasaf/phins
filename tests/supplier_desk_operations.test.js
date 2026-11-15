"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const html = fs.readFileSync(
  path.join(__dirname, "../web_portal/static/supplier-portal.html"),
  "utf8"
);
const start = html.indexOf("function supplierOperationsOpen");
const end = html.indexOf("function renderUnifiedDesk", start);
assert.ok(start > 0 && end > start, "supplierOperationsOpen is missing");
const source = html.slice(start, end);
const supplierOperationsOpen = vm.runInNewContext(source + "\nsupplierOperationsOpen;");

const failedRead = null;
const approved = supplierOperationsOpen({ role: "supplier" }, failedRead);
assert.strictEqual(approved.loadOperations, true);
assert.strictEqual(approved.editsOpen, false);

const closed = supplierOperationsOpen(
  { role: "supplier" },
  { desk: { writes_open: false, approval: { status: "suspended" } } }
);
assert.strictEqual(closed.loadOperations, true);
assert.strictEqual(closed.editsOpen, false);

const open = supplierOperationsOpen(
  { role: "supplier" },
  { desk: { writes_open: true } }
);
assert.strictEqual(open.loadOperations, true);
assert.strictEqual(open.editsOpen, true);

const agent = supplierOperationsOpen({ role: "agent" }, failedRead);
assert.strictEqual(agent.loadOperations, false);
assert.strictEqual(agent.editsOpen, false);

const boot = html.slice(html.indexOf("DOMContentLoaded"), html.indexOf("keydown"));
assert.ok(boot.includes("supplierOperationsOpen(session, desk)"));
assert.ok(boot.includes("deskWritesOpen = gate.editsOpen"));
assert.ok(boot.includes("gate.loadOperations"));
assert.ok(boot.includes("loadSupplierInfo()"));
assert.ok(boot.includes("loadOffers()"));
assert.ok(boot.includes("refreshOrders()"));
assert.ok(boot.includes("loadSettlementData()"));
assert.ok(html.includes("if (!deskWritesOpen)"));
assert.ok(html.includes("deskWritesOpen ?"));
assert.ok(html.includes('class="add-offer-btn" style="display:none"'));
assert.ok(html.includes("row.projected_amount"));
