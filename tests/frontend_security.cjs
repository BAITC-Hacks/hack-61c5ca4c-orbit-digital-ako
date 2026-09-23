"use strict";

// Run from any directory: node --test tests/frontend_security.cjs
// Executes the real frontend scripts. No server, accounts, network, or packages
// are needed. This DOM facade covers authentication, not browser rendering.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const web = path.join(__dirname, "..", "money_graph", "web");
const appSource = fs.readFileSync(path.join(web, "app.js"), "utf8");
const platformSource = fs.readFileSync(path.join(web, "platform.js"), "utf8");
const html = fs.readFileSync(path.join(web, "index.html"), "utf8");
const flush = () => new Promise(resolve => setImmediate(resolve));

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
}

class Events {
  listeners = new Map();
  addEventListener(type, callback) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(callback);
  }
  dispatchEvent(event) {
    for (const callback of this.listeners.get(event.type) || []) callback(event);
    return true;
  }
  async emit(type, fields = {}) {
    const event = {type, target: this, preventDefault() {}, ...fields};
    await Promise.all((this.listeners.get(type) || []).map(callback => callback(event)));
  }
}

class Element extends Events {
  constructor(tag = "div", attributes = {}) {
    super();
    this.tagName = tag.toUpperCase();
    this.attributes = attributes;
    this.id = attributes.id || "";
    this.dataset = Object.fromEntries(Object.entries(attributes)
      .filter(([key]) => key.startsWith("data-")).map(([key, value]) => [key.slice(5), value]));
    this.children = [];
    this.controls = [];
    this.style = {};
    this.hidden = "hidden" in attributes;
    this.disabled = "disabled" in attributes;
    this.open = false;
    this.value = this.defaultValue = attributes.value || "";
    this.files = [];
    this.resetCount = 0;
    const classes = new Set((attributes.class || "").split(/\s+/));
    this.classList = {
      contains: name => classes.has(name),
      toggle(name, enabled = !classes.has(name)) { enabled ? classes.add(name) : classes.delete(name); },
    };
  }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return (this.text || "") + this.children.map(child => child.textContent).join(""); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.text = ""; this.children = children; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  removeAttribute(key) { delete this.attributes[key]; }
  querySelector(selector) {
    if (selector === "button[type=submit]") {
      return this.controls.find(control => control.tagName === "BUTTON" && control.attributes.type === "submit");
    }
    throw new Error(`Unimplemented element selector: ${selector}`);
  }
  reset() {
    this.resetCount++;
    for (const control of this.controls) {
      control.value = control.defaultValue;
      control.files = [];
    }
  }
  close() { this.open = false; }
  showModal() { this.open = true; }
}

function attributes(source) {
  return Object.fromEntries([...source.matchAll(/([\w-]+)(?:="([^"]*)")?/g)]
    .map(match => [match[1], match[2] || ""]));
}

function documentFixture() {
  const document = new Events();
  const byId = new Map();
  const elements = [];
  for (const match of html.matchAll(/<([a-z][\w-]*)\b([^>]*)>/gi)) {
    const node = new Element(match[1], attributes(match[2]));
    elements.push(node);
    if (node.id) byId.set(node.id, node);
  }
  for (const match of html.matchAll(/<form\b([^>]*)>([\s\S]*?)<\/form>/gi)) {
    const form = byId.get(attributes(match[1]).id);
    for (const control of match[2].matchAll(/<(input|select|textarea|button)\b([^>]*)>/gi)) {
      const attrs = attributes(control[2]);
      form.controls.push(byId.get(attrs.id) || new Element(control[1], attrs));
    }
    form.elements = Object.fromEntries(form.controls.filter(node => node.attributes.name)
      .map(node => [node.attributes.name, node]));
  }
  document.getElementById = id => {
    assert.ok(byId.has(id), `Unknown DOM id: ${id}`);
    return byId.get(id);
  };
  document.createElement = tag => new Element(tag);
  document.body = elements.find(node => node.tagName === "BODY");
  document.hidden = false;
  document.querySelectorAll = selector => {
    if (selector === "form") return elements.filter(node => node.tagName === "FORM");
    if (selector === "dialog[open]" || selector === "details[open]") {
      const tag = selector.split("[")[0].toUpperCase();
      return elements.filter(node => node.tagName === tag && node.open);
    }
    if (selector.startsWith(".")) return elements.filter(node => node.classList.contains(selector.slice(1)));
    const attr = /^(button)?\[([\w-]+)\]$/.exec(selector);
    assert.ok(attr, `Unimplemented document selector: ${selector}`);
    return elements.filter(node => (!attr[1] || node.tagName === "BUTTON") && attr[2] in node.attributes);
  };
  document.querySelector = selector => document.querySelectorAll(selector)[0] || null;
  return document;
}

function account(id, overrides = {}) {
  return {user: {id, username: id, role: "admin", must_change_password: false, ...overrides}, csrf_token: `csrf-${id}`};
}

function harness() {
  const document = documentFixture();
  const requests = [];
  const caseLoads = [];
  const context = vm.createContext({
    document, window: new Events(), console, Headers, Event, URLSearchParams, AbortController,
    location: {search: "", reload() {}}, history: {replaceState() {}}, localStorage: {},
    requestAnimationFrame() {}, matchMedia: () => ({matches: false}),
    FormData: class {
      constructor(form) { this.form = form; }
      *[Symbol.iterator]() {
        for (const node of this.form.controls) if (node.attributes.name) yield [node.attributes.name, node.value];
      }
    },
    caseLoads,
    checkpoint: null,
    fetch(url, config) {
      const headers = deferred(), body = deferred(), started = deferred();
      const authenticatedUser = vm.runInContext("session.user?.id", context);
      const request = {
        url, config, bodyStarted: started.promise,
        headers(status = 200, values = {}) {
          const responseHeaders = new Headers(values);
          if (authenticatedUser && !responseHeaders.has("X-Account-Id")) responseHeaders.set("X-Account-Id", authenticatedUser);
          headers.resolve({status, ok: status >= 200 && status < 300, headers: responseHeaders,
            json() { started.resolve(); return body.promise; }});
        },
        finish(value, status = 200, values = {}) { this.headers(status, values); body.resolve(value); },
      };
      requests.push(request);
      return headers.promise;
    },
  });
  vm.runInContext(appSource, context, {filename: "app.js"});
  // Skip only graph loading/rendering. The API helper and auth handlers remain
  // the real code. The optional checkpoint models a session change between a
  // fulfilled API promise and its caller's continuation, without timing sleeps.
  vm.runInContext(`
    loadCases = async preferred => { caseLoads.push(preferred); };
    const originalApiForTest = api;
    api = async (...args) => {
      const body = await originalApiForTest(...args);
      if (checkpoint) checkpoint(args[0]);
      return body;
    };
  `, context);
  vm.runInContext(platformSource, context, {filename: "platform.js"});
  const exports = vm.runInContext("({session, state, api, showLogin, enterWorkspace, setView})", context);
  return {
    ...exports, context, document, requests, caseLoads,
    element: id => document.getElementById(id),
    signIn: id => exports.enterWorkspace(account(id)),
    async guest() {
      assert.equal(requests[0].url, "/api/auth/me");
      requests[0].finish({detail: "Authentication required"}, 401);
      await flush();
      assert.equal(exports.session.user, null);
    },
    submit(id) {
      const form = document.getElementById(id);
      return form.emit("submit", {submitter: form.querySelector("button[type=submit]")});
    },
  };
}

test("current-session JSON succeeds with CSRF and private fetch settings", async () => {
  const h = harness(); await h.guest(); await h.signIn("A");
  const pending = h.api("/api/cases/demo/ask", {method: "POST", body: "{}"});
  const request = h.requests.at(-1);
  assert.equal(request.config.headers.get("X-CSRF-Token"), "csrf-A");
  assert.equal(request.config.credentials, "same-origin");
  assert.equal(request.config.cache, "no-store");
  const payload = {answer: "A-only evidence"};
  request.finish(payload);
  assert.equal(await pending, payload);
});

for (const nextAccount of ["B", "A"]) {
  test(`late JSON is dropped after switching A to a new ${nextAccount} session`, async () => {
    const h = harness(); await h.guest(); await h.signIn("A");
    const pending = h.api("/api/cases/demo/reports");
    const rejected = assert.rejects(pending, /Сессия изменилась/);
    const request = h.requests.at(-1);
    request.headers(); await request.bodyStarted;
    const previousGeneration = h.session.generation;
    h.showLogin(); await h.signIn(nextAccount);
    assert.ok(h.session.generation > previousGeneration);
    request.finish([{title: "A-only report"}]);
    await rejected;
    assert.equal(h.session.user.id, nextAccount);
  });
}

test("a delayed 401 from an old generation cannot log out the new session", async () => {
  const h = harness(); await h.guest(); await h.signIn("A");
  const pending = h.api("/api/cases/demo/reports");
  const rejected = assert.rejects(pending, /Сессия изменилась/);
  const request = h.requests.at(-1);
  request.headers(401); await request.bodyStarted;
  h.showLogin(); await h.signIn("A");
  request.finish({detail: "Authentication required"});
  await rejected;
  assert.equal(h.session.user.id, "A");
  assert.equal(h.element("application").hidden, false);
});

test("late admin-create JSON cannot render its temporary password under B", async () => {
  const h = harness(); await h.guest(); await h.signIn("A");
  const pending = h.submit("user-form");
  const request = h.requests.at(-1);
  assert.equal(request.url, "/api/admin/users");
  request.headers(201); await request.bodyStarted;
  h.showLogin(); await h.signIn("B");
  request.finish({user: {username: "new-user"}, temporary_password: "SYNTHETIC-SECRET"});
  await pending;
  assert.equal(h.session.user.id, "B");
  assert.ok(!h.element("user-message").textContent.includes("SYNTHETIC-SECRET"));
});

test("showLogin resets every form, including selected Parquet files and admin fields", async () => {
  const h = harness(); await h.guest(); await h.signIn("A");
  const forms = h.document.querySelectorAll("form");
  const before = forms.map(form => form.resetCount);
  const upload = h.element("upload-form");
  for (const form of forms) for (const control of form.controls) {
    control.value = "A-private-input";
    if (control.attributes.type === "file") control.files = [{name: "A-private.parquet"}];
  }
  const privatePanels = ["user-message", "document-list", "report-list", "transaction-rows",
    "transaction-pair", "downloads", "graph-subtitle", "ask-answer"];
  for (const id of privatePanels) h.element(id).textContent = "SYNTHETIC-SECRET";
  h.element("upload-dialog").showModal();
  h.state.nodes.set("private-gid", {});
  h.state.workspaces.set("private-case", {});
  const generation = h.session.generation;
  h.showLogin();
  assert.ok(h.session.generation > generation);
  assert.equal(h.session.user, null);
  assert.equal(h.session.csrf, null);
  forms.forEach((form, index) => {
    assert.ok(form.resetCount > before[index], `${form.id} must reset`);
    for (const control of form.controls) {
      assert.equal(control.value, control.defaultValue);
      assert.equal(control.files.length, 0);
    }
  });
  for (const name of ["nodes", "edges", "transactions"]) assert.equal(upload.elements[name].files.length, 0);
  assert.equal(h.element("upload-dialog").open, false);
  for (const id of privatePanels) assert.equal(h.element(id).textContent, "", `${id} must clear`);
  assert.equal(h.state.nodes.size, 0);
  assert.equal(h.state.workspaces.size, 0);
});

test("leaving the admin view clears its one-time password", async () => {
  const h = harness(); await h.guest(); await h.signIn("A");
  h.element("user-message").textContent = "SYNTHETIC-SECRET";
  await h.setView("investigation", false);
  assert.equal(h.element("user-message").textContent, "");
});

test("bootstrap holds the login button until its JSON and continuation settle", async () => {
  const h = harness();
  const button = h.element("login-form").querySelector("button[type=submit]");
  assert.equal(button.disabled, true);
  h.requests[0].headers(); await h.requests[0].bodyStarted;
  assert.equal(button.disabled, true);
  h.requests[0].finish(account("A")); await flush();
  assert.equal(button.disabled, false);
  assert.equal(h.session.user.id, "A");
  assert.deepEqual(h.caseLoads, ["demo"]);
});

test("anonymous bootstrap 401 shows login without broadcasting auth-expired", async () => {
  const h = harness();
  let expired = 0;
  h.context.window.addEventListener("auth-expired", () => { expired++; });
  await h.guest();
  assert.equal(expired, 0);
  assert.equal(h.element("application").hidden, true);
  assert.equal(h.element("login-screen").hidden, false);
  assert.equal(h.element("login-form").querySelector("button[type=submit]").disabled, false);
});

test("stale bootstrap JSON cannot replace a subsequently established session", async () => {
  const h = harness();
  h.requests[0].headers(); await h.requests[0].bodyStarted;
  h.showLogin(); await h.signIn("B");
  h.requests[0].finish(account("A")); await flush();
  assert.equal(h.session.user.id, "B");
  assert.deepEqual(h.caseLoads, ["demo"]);
});

test("bootstrap passes its original generation to the workspace continuation", async () => {
  const h = harness();
  h.context.checkpoint = url => { if (url === "/api/auth/me") h.showLogin(); };
  h.requests[0].finish(account("A")); await flush();
  assert.equal(h.session.user, null);
  assert.equal(h.element("application").hidden, true);
  assert.deepEqual(h.caseLoads, []);
  assert.equal(h.element("login-form").querySelector("button[type=submit]").disabled, false);
});

test("stale login JSON cannot replace a subsequently established session", async () => {
  const h = harness(); await h.guest();
  const pending = h.submit("login-form");
  const request = h.requests.at(-1);
  assert.equal(request.url, "/api/auth/login");
  request.headers(); await request.bodyStarted;
  h.showLogin(); await h.signIn("B");
  request.finish(account("A")); await pending;
  assert.equal(h.session.user.id, "B");
  assert.deepEqual(h.caseLoads, ["demo"]);
});

test("login passes its original generation to the workspace continuation", async () => {
  const h = harness(); await h.guest();
  h.context.checkpoint = url => { if (url === "/api/auth/login") h.showLogin(); };
  const pending = h.submit("login-form");
  h.requests.at(-1).finish(account("A")); await pending;
  assert.equal(h.session.user, null);
  assert.equal(h.element("application").hidden, true);
  assert.deepEqual(h.caseLoads, []);
});

test("visibility revalidation clears A when the shared cookie now belongs to B", async () => {
  const h = harness(); await h.guest(); await h.signIn("A");
  h.element("report-list").textContent = "A-private-report";
  const pending = h.document.emit("visibilitychange");
  assert.equal(h.requests.at(-1).url, "/api/auth/me");
  h.requests.at(-1).finish(account("B")); await pending;
  assert.equal(h.session.user, null);
  assert.equal(h.element("report-list").textContent, "");
  assert.equal(h.element("application").hidden, true);
});

test("two-tab cookie switch: a B response cannot reach a tab still displaying A", async () => {
  const h = harness(); await h.guest(); await h.signIn("A");
  // Another tab has changed the shared HttpOnly cookie to B. This tab's local
  // generation has not changed. Its focus /me check is still in flight while
  // another GET, authenticated by the browser's B cookie, completes first.
  const focus = h.document.emit("visibilitychange");
  const identityRequest = h.requests.at(-1);
  const pending = h.api("/api/cases/demo/documents");
  const request = h.requests.at(-1);
  const rejected = assert.rejects(pending, /Сессия|Аккаунт|session|account/i);
  request.finish([{id: "b-document", title: "B-private-document"}], 200, {"X-Account-Id": "B"});
  try {
    await rejected;
    assert.equal(h.session.user, null);
    assert.equal(h.element("application").hidden, true);
  } finally {
    identityRequest.finish(account("B"));
    await focus;
  }
});
