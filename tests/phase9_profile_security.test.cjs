const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "..", "app", "static", "profile.js"),
  "utf8",
);

class MockElement {
  constructor(tag = "div") {
    this.tagName = tag;
    this.children = [];
    this.textContent = "";
    this.className = "";
    this.style = {};
    this._innerHTML = undefined;
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = [...children]; }
  set innerHTML(value) { this._innerHTML = value; }
  get innerHTML() { return this._innerHTML; }
}

test("membership card renders hostile plan/status values through text nodes only", async () => {
  const elements = {
    membershipCardWrap: new MockElement("section"),
    expiryWarning: new MockElement("aside"),
    expiryWarningText: new MockElement("span"),
  };
  const payload = {
    success: true,
    request: {
      plan_name: '<img src=x onerror="alert(1)">',
      status: '<svg onload="alert(2)">',
      request_date: "2026-10-01",
      start_date: null,
      end_date: null,
    },
  };
  const context = {
    document: {
      addEventListener() {},
      getElementById: (id) => elements[id] || null,
      createElement: (tag) => new MockElement(tag),
    },
    fetch: async () => ({
      ok: true,
      status: 200,
      json: async () => payload,
    }),
    Date,
    Number,
  };
  vm.runInNewContext(source, context, { filename: "profile.js" });
  await context.loadMembershipCard();

  const card = elements.membershipCardWrap.children[0];
  assert.equal(card.className, "membership-card");
  const [header, planRow] = card.children;
  const statusBadge = header.children[1];
  assert.equal(statusBadge.textContent, '<svg onload="alert(2)">');
  assert.equal(statusBadge.className, "status-badge unknown");
  assert.equal(planRow.children[1].textContent, '<img src=x onerror="alert(1)">');
  assert.equal(elements.membershipCardWrap.innerHTML, undefined);
});
