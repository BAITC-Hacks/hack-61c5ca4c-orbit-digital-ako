"use strict";

// Run from the repository root: node --test tests/test_web_state.cjs
// Exercise the shipped loader and retry handler; only DOM/graph rendering and
// HTTP transport are replaced. No browser package, server or API key is needed.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const appPath = path.join(__dirname, "..", "money_graph", "web", "app.js");

class Element {
  constructor() {
    this.children = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this.dataset = {};
    this.style = {};
    this.value = "";
    this.textContent = "";
    this.inert = false;
    this.hidden = false;
    this.disabled = false;
    this.classes = new Set();
    this.classList = {
      toggle: (name, enabled) => enabled ? this.classes.add(name) : this.classes.delete(name),
      contains: name => this.classes.has(name),
    };
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name); }
  addEventListener(type, listener) { this.listeners.set(type, listener); }
}

function graph(label) {
  return {
    label,
    nodes: [{ gid: "101", priority_score: 1 }],
    edges: [],
    top: [{ gid: "101" }],
    summary: { nodes: 1, runtime_sec: 0.01 },
  };
}

function createHarness() {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const presets = ["explain", "common_recipients", "paths", "missing_data"].map(mode => {
    const button = new Element();
    button.dataset.assistantMode = mode;
    return button;
  });
  const requests = [];
  const document = {
    getElementById: element,
    createElement: () => new Element(),
    querySelector: selector => element("selector:" + selector),
    querySelectorAll: selector => selector === "[data-assistant-mode]" ? presets : [],
    addEventListener() {},
  };
  const context = vm.createContext({
    document, Intl, AbortController, URLSearchParams, Headers, Event,
    CustomEvent: class extends Event { constructor(type, options) { super(type); this.detail=options?.detail; } },
    window: new EventTarget(),
    history: { replaceState() {} },
    localStorage: { getItem: () => null, setItem() {} },
    fetch(url, options) {
      // Deliberately allow a reply after abort: the version guard must also
      // protect against responses already queued or transports ignoring abort.
      return new Promise((resolve, reject) => requests.push({
        url, options, resolve, reject, settled: false,
      }));
    },
  });

  const source = fs.readFileSync(appPath, "utf8");
  // Authentication in platform.js now starts loading. Evaluate the whole app;
  // a private request during script initialization would be a regression.
  vm.runInContext(source, context, { filename: appPath });
  assert.equal(requests.length, 0, "app.js must not fetch private data before login");
  vm.runInContext("session.user={id:'test-analyst',must_change_password:false}; session.csrf='test-csrf'; renderGraph = () => {}; renderAll = () => renderAssistant();", context);

  function request(url) {
    const pending = requests.find(item => item.url === url && !item.settled);
    assert.ok(pending, "Expected a pending request for " + url);
    pending.settled = true;
    return pending;
  }
  function respond(url, data, status = 200) {
    request(url).resolve({ ok: status >= 200 && status < 300, status, headers: new Headers({"X-Account-Id":"test-analyst"}), json: async () => data });
  }
  return {
    element,
    loadCase: vm.runInContext("loadCase", context),
    askAssistant: vm.runInContext("askAssistant", context),
    assistant: vm.runInContext("assistant", context),
    state: vm.runInContext("state", context),
    requests,
    respond,
    reject: (url, error) => request(url).reject(error),
    retry: () => element("retry").listeners.get("click")(),
  };
}

test("assistant failure shows the server reason once and preserves the question and selection", async () => {
  const h = createHarness();
  const initial = h.loadCase("demo");
  h.respond("/api/cases/demo/graph", graph("Demo"));
  await initial;
  h.assistant.configured = true;
  h.assistant.gids = ["101"];
  const question = "Почему этот узел стоит проверить?";
  h.element("assistant-question").value = question;

  const asking = h.askAssistant("question");
  const reason = "Не удалось получить ответ: нет соединения с OpenAI. Проверьте подключение.";
  h.respond("/api/cases/demo/assistant", { detail: reason }, 503);
  await asking;

  assert.equal(h.element("assistant-error").textContent, reason);
  assert.equal(h.element("assistant-error").hidden, false);
  assert.equal(h.element("assistant-result").children.length, 1);
  assert.match(h.element("assistant-result").children[0].textContent, /^Ответ не получен\./);
  assert.doesNotMatch(h.element("assistant-result").children[0].textContent, /Выберите действие/);
  assert.equal(h.element("assistant-question").value, question);
  assert.deepEqual([...h.assistant.gids], ["101"]);
  assert.equal(h.assistant.busy, false);
  assert.equal(h.element("assistant-submit").disabled, false);
  assert.equal(h.requests.filter(request => request.url.endsWith("/assistant")).length, 1, "no automatic retry");
});

test("a late assistant failure does not paint an error after the case selection changes", async () => {
  const h = createHarness();
  const initial = h.loadCase("demo");
  h.respond("/api/cases/demo/graph", graph("Demo"));
  await initial;
  h.assistant.configured = true;
  h.assistant.gids = ["101"];
  h.element("assistant-question").value = "Объясни роль узла";
  const asking = h.askAssistant("question");
  const replacement = h.loadCase("next");
  h.reject("/api/cases/demo/assistant", new Error("Old provider failure"));
  await asking;

  assert.equal(h.element("assistant-error").hidden, true);
  assert.doesNotMatch(h.element("assistant-result").children[0].textContent, /Ответ не получен/);
  assertLoading(h);
  h.respond("/api/cases/next/graph", graph("Next"));
  await replacement;
  assertInteractive(h);
});

function assertLoading(harness) {
  assert.equal(harness.element("workspace").inert, true, "workspace is locked while loading");
  assert.equal(harness.element("assistant-panel").inert, true, "assistant is locked while loading");
  assert.equal(harness.element("workspace").getAttribute("aria-busy"), "true");
  assert.equal(harness.element("retry").hidden, true);
}

function assertInteractive(harness) {
  assert.equal(harness.element("workspace").inert, false, "workspace is interactive");
  assert.equal(harness.element("assistant-panel").inert, false, "assistant is interactive");
  assert.equal(harness.element("workspace").getAttribute("aria-busy"), "false");
}

test("first successful case load unlocks both workspace and assistant", async () => {
  const h = createHarness();
  const loading = h.loadCase("demo");
  assertLoading(h);
  h.respond("/api/cases/demo/graph", graph("Demo"));
  await loading;

  assert.equal(h.state.caseId, "demo");
  assert.equal(h.state.data.label, "Demo");
  assertInteractive(h);
  assert.equal(h.element("assistant-add").disabled, false, "selected node can be added");
  assert.equal(h.element("retry").hidden, true);
});

test("failed initial load stays locked; actual retry handler unlocks after success", async () => {
  const h = createHarness();
  const failed = h.loadCase("demo");
  h.respond("/api/cases/demo/graph", { detail: "Temporary error" }, 503);
  await failed;

  assert.equal(h.state.data, null);
  assert.equal(h.element("workspace").inert, true);
  assert.equal(h.element("assistant-panel").inert, true);
  assert.equal(h.element("retry").hidden, false);
  assert.match(h.element("status").textContent, /Temporary error/);

  const retrying = h.retry();
  h.respond("/api/cases", [{ id: "demo", label: "Demo" }]);
  await new Promise(setImmediate);
  assertLoading(h);
  h.respond("/api/cases/demo/graph", graph("Recovered"));
  await retrying;

  assert.equal(h.state.data.label, "Recovered");
  assertInteractive(h);
  assert.equal(h.element("retry").hidden, true);
});

test("failed replacement restores access to the previously loaded case", async () => {
  const h = createHarness();
  const initial = h.loadCase("demo");
  h.respond("/api/cases/demo/graph", graph("Existing case"));
  await initial;
  const previousData = h.state.data;

  const replacement = h.loadCase("broken");
  assertLoading(h);
  h.respond("/api/cases/broken/graph", { detail: "Case is unavailable" }, 500);
  await replacement;

  assert.equal(h.state.data, previousData);
  assert.equal(h.state.caseId, "demo");
  assert.equal(h.element("case-select").value, "demo");
  assertInteractive(h);
  assert.equal(h.element("retry").hidden, false);
});

for (const outcome of ["success", "failure"]) {
  test("stale " + outcome + " cannot unlock or overwrite a newer pending case", async () => {
    const h = createHarness();
    const initial = h.loadCase("demo");
    h.respond("/api/cases/demo/graph", graph("Existing case"));
    await initial;

    const older = h.loadCase("older");
    const newer = h.loadCase("newer");
    const loadingMessage = h.element("status").textContent;
    assertLoading(h);
    if (outcome === "success") h.respond("/api/cases/older/graph", graph("Stale case"));
    else h.reject("/api/cases/older/graph", new Error("Stale network failure"));
    await older;

    assertLoading(h);
    assert.equal(h.element("status").textContent, loadingMessage);
    assert.equal(h.state.caseId, "demo");
    assert.equal(h.state.data.label, "Existing case");

    h.respond("/api/cases/newer/graph", graph("Newest case"));
    await newer;
    assertInteractive(h);
    assert.equal(h.state.caseId, "newer");
    assert.equal(h.state.data.label, "Newest case");
  });
}
