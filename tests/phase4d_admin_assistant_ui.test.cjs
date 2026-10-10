"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../app/static/admin-assistant.js"),
  "utf8",
);

class MockElement {
  constructor(id = "") {
    this.id = id;
    this.listeners = Object.create(null);
    this.attributes = Object.create(null);
    this.children = [];
    this.textContent = "";
    this.value = "";
    this.hidden = false;
    this.disabled = false;
    this.scrollHeight = 0;
    this.scrollTop = 0;
  }

  addEventListener(name, handler) {
    (this.listeners[name] ||= []).push(handler);
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  append(...children) {
    this.children.push(...children);
    this.scrollHeight = this.children.length;
  }

  focus() {
    this.focused = true;
  }

  async fire(name, event = {}) {
    let prevented = false;
    const evt = {
      ...event,
      preventDefault() { prevented = true; },
    };
    for (const handler of this.listeners[name] || []) await handler(evt);
    return { prevented };
  }
}

function harness(fetchImpl) {
  const ids = [
    "adminAssistantForm",
    "assistantQuestion",
    "assistantSendButton",
    "assistantConversation",
    "assistantLoading",
    "assistantValidationError",
    "assistantCharacterCount",
  ];
  const elements = Object.fromEntries(ids.map((id) => [id, new MockElement(id)]));
  let onReady;
  const document = {
    getElementById: (id) => elements[id] || null,
    createElement: (tag) => {
      const element = new MockElement();
      element.tagName = tag.toUpperCase();
      return element;
    },
    addEventListener(name, handler) {
      if (name === "DOMContentLoaded") onReady = handler;
    },
  };
  const context = { document, fetch: fetchImpl };
  vm.runInNewContext(source, context, { filename: "admin-assistant.js" });
  assert.equal(typeof onReady, "function", "script registers dashboard initialization");
  onReady();
  return { elements };
}

function response(status, payload, headers = {}) {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: { get: (name) => headers[name] || null },
    async json() { return payload; },
  };
}

function messageTexts(conversation) {
  return conversation.children.map((article) => article.children[1].textContent);
}

test("sends exact Phase 4C JSON and renders question and answer as plain text", async () => {
  let sent;
  const { elements } = harness(async (url, options) => {
    sent = { url, options };
    return response(200, { success: true, status: "ok", answer: "<script>nope()</script>" });
  });
  const question = "<img src=x onerror=alert(1)>";
  elements.assistantQuestion.value = question;
  await elements.adminAssistantForm.fire("submit");

  assert.equal(sent.url, "/api/admin/assistant/ask");
  assert.equal(sent.options.method, "POST");
  assert.equal(sent.options.headers["Content-Type"], "application/json");
  assert.equal(sent.options.credentials, "include");
  assert.deepEqual(JSON.parse(sent.options.body), { question });
  assert.equal(elements.assistantQuestion.value, "");
  assert.deepEqual(messageTexts(elements.assistantConversation), [question, "<script>nope()</script>"]);
  assert.equal(elements.assistantConversation.children[0].children[1].tagName, "P");
  assert.equal(elements.assistantConversation.children[1].children[1].tagName, "P");
  assert.equal(elements.assistantSendButton.disabled, false);
  assert.equal(elements.assistantLoading.hidden, true);
});

test("displays insufficient-data results distinctly", async () => {
  const { elements } = harness(async () => response(200, {
    success: true,
    status: "insufficient_data",
    answer: "There is not enough approved data.",
  }));
  elements.assistantQuestion.value = "Can you answer this?";
  await elements.adminAssistantForm.fire("submit");
  assert.match(elements.assistantConversation.children[1].className, /assistant-message-insufficient/);
  assert.equal(elements.assistantConversation.children[1].children[0].textContent, "Not enough data");
});

test("validates empty and over-limit questions without sending", async () => {
  let calls = 0;
  const { elements } = harness(async () => { calls += 1; return response(200, {}); });
  await elements.adminAssistantForm.fire("submit");
  assert.match(elements.assistantValidationError.textContent, /Enter a question/);
  assert.equal(elements.assistantQuestion.attributes["aria-invalid"], "true");
  elements.assistantQuestion.value = "x".repeat(1201);
  await elements.adminAssistantForm.fire("submit");
  assert.match(elements.assistantValidationError.textContent, /1,200 characters/);
  assert.equal(calls, 0);
});

test("prevents duplicate submissions while a request is pending", async () => {
  let calls = 0;
  let resolveFetch;
  const pending = new Promise((resolve) => { resolveFetch = resolve; });
  const { elements } = harness(() => { calls += 1; return pending; });
  elements.assistantQuestion.value = "How many accounts?";
  const first = elements.adminAssistantForm.fire("submit");
  assert.equal(elements.assistantSendButton.disabled, true);
  assert.equal(elements.assistantQuestion.disabled, true);
  assert.equal(elements.assistantLoading.hidden, false);
  await elements.adminAssistantForm.fire("submit");
  assert.equal(calls, 1);
  resolveFetch(response(200, { success: true, status: "ok", answer: "Five." }));
  await first;
  assert.equal(elements.assistantSendButton.disabled, false);
  assert.equal(elements.assistantQuestion.disabled, false);
  assert.equal(elements.assistantLoading.hidden, true);
});

test("handles 401, 403, and 429 safely, including Retry-After", async (t) => {
  const cases = [
    [401, {}, /session may have expired/],
    [403, {}, /request was blocked/],
    [429, {}, /wait 17 seconds/],
  ];
  for (const [status, payload, expected] of cases) {
    await t.test(String(status), async () => {
      const { elements } = harness(async () => response(status, payload, { "Retry-After": "17" }));
      elements.assistantQuestion.value = "How many accounts?";
      await elements.adminAssistantForm.fire("submit");
      assert.match(messageTexts(elements.assistantConversation)[1], expected);
      assert.equal(elements.assistantSendButton.disabled, false);
    });
  }
});

test("handles server errors, malformed JSON/shapes, and network failure without exposing details or sticking", async (t) => {
  const cases = [
    ["HTTP 400", async () => response(400, {}), /question could not be accepted/],
    ["HTTP 413", async () => response(413, {}), /request was too large/],
    ["HTTP 415", async () => response(415, {}), /format was not accepted/],
    ["HTTP 500", async () => response(500, {}), /could not complete this request/],
    ["HTTP 502", async () => response(502, {}), /could not provide an answer/],
    ["HTTP 503", async () => response(503, { success: false, status: "error", error: { code: "data_unavailable", message: "private detail" } }), /temporarily unavailable/],
    ["HTTP 504", async () => response(504, {}), /took too long to respond/],
    ["malformed JSON", async () => ({ ok: true, status: 200, headers: { get: () => null }, async json() { throw new Error("SECRET parse detail"); } }), /unexpected response/],
    ["unexpected shape", async () => response(200, { success: true, status: "unknown", answer: "bad" }), /unexpected response/],
    ["network failure", async () => { throw new Error("SECRET network detail"); }, /Could not reach/],
  ];
  for (const [name, fetchImpl, expected] of cases) {
    await t.test(name, async () => {
      const { elements } = harness(fetchImpl);
      elements.assistantQuestion.value = "How many accounts?";
      await elements.adminAssistantForm.fire("submit");
      const text = messageTexts(elements.assistantConversation)[1];
      assert.match(text, expected);
      assert.doesNotMatch(text, /SECRET|private detail/);
      assert.equal(elements.assistantSendButton.disabled, false);
      assert.equal(elements.assistantLoading.hidden, true);
    });
  }
});
