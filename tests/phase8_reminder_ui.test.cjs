const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "..", "app", "static", "membership-reminders.js"),
  "utf8",
);

class MockElement {
  constructor(id = "") {
    this.id = id;
    this.children = [];
    this.listeners = {};
    this.disabled = false;
    this.checked = false;
    this.value = "";
    this.textContent = "";
    this.classNames = new Set();
    this.classList = {
      toggle: (name, enabled) => {
        if (enabled) this.classNames.add(name);
        else this.classNames.delete(name);
      },
      contains: (name) => this.classNames.has(name),
    };
  }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = [...children]; }
}

function createHarness(responses) {
  const ids = [
    "reminderPreferencesForm",
    "reminderEnabled",
    "reminderLeadTimeGroup",
    "reminderLeadTimeOptions",
    "saveReminderPreferencesBtn",
    "reminderPreferencesStatus",
  ];
  const elements = Object.fromEntries(ids.map((id) => [id, new MockElement(id)]));
  const calls = [];
  const context = {
    document: {
      getElementById: (id) => elements[id] || null,
      createElement: (tag) => new MockElement(tag),
    },
    fetch: async (url, options) => {
      calls.push({ url, options });
      const next = responses.shift();
      if (next instanceof Error) throw next;
      return {
        ok: next.ok,
        status: next.status,
        json: async () => next.data,
      };
    },
  };
  vm.runInNewContext(source, context, { filename: "membership-reminders.js" });
  return { context, elements, calls };
}

const savedOff = {
  success: true,
  preferences: { enabled: false, lead_days: [7, 1] },
  supported_lead_days: [7, 3, 1],
};
const savedOn = {
  success: true,
  preferences: { enabled: true, lead_days: [3] },
  supported_lead_days: [7, 3, 1],
};

test("loads saved preferences and renders configured choices from text-safe DOM nodes", async () => {
  const h = createHarness([{ ok: true, status: 200, data: savedOff }]);
  await h.context.initMembershipReminderSettings();

  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].url, "/api/membership/reminder-preferences");
  assert.equal(h.calls[0].options.method, "GET");
  assert.equal(h.calls[0].options.credentials, "same-origin");
  assert.equal(h.elements.reminderEnabled.checked, false);
  const inputs = h.elements.reminderLeadTimeOptions.children.map((label) => label.children[0]);
  assert.deepEqual(inputs.map((input) => input.value), ["7", "3", "1"]);
  assert.deepEqual(inputs.map((input) => input.checked), [true, false, true]);
  assert.equal(h.elements.saveReminderPreferencesBtn.disabled, false);
  assert.match(h.elements.reminderPreferencesStatus.textContent, /currently off/i);
});

test("saves the selected settings and repaints from the server-confirmed response", async () => {
  const h = createHarness([
    { ok: true, status: 200, data: savedOff },
    { ok: true, status: 200, data: savedOn },
  ]);
  await h.context.initMembershipReminderSettings();
  h.elements.reminderEnabled.checked = true;
  const inputs = h.elements.reminderLeadTimeOptions.children.map((label) => label.children[0]);
  inputs.find((input) => input.value === "7").checked = false;
  inputs.find((input) => input.value === "1").checked = false;
  inputs.find((input) => input.value === "3").checked = true;
  let prevented = false;
  await h.elements.reminderPreferencesForm.listeners.submit({
    preventDefault() { prevented = true; },
  });

  assert.equal(prevented, true);
  assert.equal(h.calls.length, 2);
  assert.equal(h.calls[1].options.method, "PUT");
  assert.equal(h.calls[1].options.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(h.calls[1].options.body), { enabled: true, lead_days: [3] });
  assert.equal(h.elements.reminderEnabled.checked, true);
  assert.match(h.elements.reminderPreferencesStatus.textContent, /saved/i);
  assert.equal(h.elements.reminderPreferencesStatus.classList.contains("success"), true);
});

test("blocks enabling with no selected lead time before making a write request", async () => {
  const h = createHarness([{ ok: true, status: 200, data: savedOff }]);
  await h.context.initMembershipReminderSettings();
  h.elements.reminderEnabled.checked = true;
  for (const label of h.elements.reminderLeadTimeOptions.children) {
    label.children[0].checked = false;
  }
  await h.elements.reminderPreferencesForm.listeners.submit({ preventDefault() {} });
  assert.equal(h.calls.length, 1);
  assert.match(h.elements.reminderPreferencesStatus.textContent, /select at least one/i);
  assert.equal(h.elements.reminderPreferencesStatus.classList.contains("error"), true);
});

test("shows a safe session-expired message for unauthenticated member settings", async () => {
  const h = createHarness([{ ok: false, status: 401, data: {
    success: false, error: { code: "unauthenticated", message: "private server detail" },
  } }]);
  await h.context.initMembershipReminderSettings();
  assert.match(h.elements.reminderPreferencesStatus.textContent, /session has expired/i);
  assert.doesNotMatch(h.elements.reminderPreferencesStatus.textContent, /private server detail/);
  assert.equal(h.elements.saveReminderPreferencesBtn.disabled, true);
});
