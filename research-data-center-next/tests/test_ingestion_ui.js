"use strict";
// Exercise the real buildless render/load functions without a browser or network.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const nodes = new Map();
function node(id) {
  if (!nodes.has(id)) nodes.set(id, {
    dataset: {}, textContent: "", innerHTML: "", hidden: false, disabled: false, open: false,
    classList: { add() {}, remove() {}, toggle() {} },
    replaceChildren() { this.innerHTML = ""; this.textContent = ""; },
    setAttribute() {}, focus() {}, close() { this.open = false; }, showModal() { this.open = true; },
  });
  return nodes.get(id);
}
const origin = "http://127.0.0.1:18766";
const context = {
  document: { getElementById: node },
  window: { location: { origin }, matchMedia: () => ({ matches: false }) },
  location: { origin }, Intl, URL, AbortController, console, setTimeout, clearTimeout,
  fetch: async () => { throw new Error("unexpected network call"); },
};
vm.createContext(context);
const source = fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8");
assert.ok(source.includes("  initialize();"));
vm.runInContext(source.replace("  initialize();", "  globalThis.subject = { renderIngestion, renderPublished, loadIngestion, clearCatalog, showAuth, updateAgentCode, state };"), context);
const subject = context.subject;
let checks = 0;
function check(condition) { assert.ok(condition); checks += 1; }

(async () => {
  for (const mode of ["not-configured", "planned", "disabled", "active", "worker-stale"]) {
    subject.renderIngestion({ mode, counts: null, jobs: [] });
    check(node("ingestion-mode").dataset.mode === mode);
    check(node("ingestion-mode").textContent.length > 0);
  }
  subject.renderIngestion({ mode: "not-configured", counts: null, jobs: [] });
  check(node("ingestion-counts").innerHTML.includes("—"));
  check(!node("ingestion-counts").innerHTML.includes("<strong>0</strong>"));
  subject.renderIngestion({ mode: "invented-active-mode" });
  check(node("ingestion-mode").dataset.mode === "unavailable");
  subject.renderIngestion({ mode: "active", counts: { submitted: 2, validating: 1, published: 4, failed: 1 },
    jobs: [{ id: "job-1", display_name: '<img src=x onerror="alert(1)">', kind: "dataset", status: "needs_information",
      reason_code: '<script>unsafe</script>', updated_at: "2026-10-27T09:00:00Z" }] });
  check(node("ingestion-counts").innerHTML.includes("<strong>3</strong>"));
  check(node("ingestion-jobs").innerHTML.includes("&lt;img"));
  check(!node("ingestion-jobs").innerHTML.includes("<img"));
  check(!node("ingestion-jobs").innerHTML.includes("<script>"));
  check(node("ingestion-jobs").innerHTML.includes("待补充说明"));
  subject.renderIngestion({ mode: "active", jobs: Array.from({ length: 30 }, (_, i) => ({ id: `j${i}`, status: "published" })) });
  check((node("ingestion-jobs").innerHTML.match(/<tr>/g) || []).length === 21);
  subject.renderPublished({ configured: true, items: [{ title: '<script>bad</script>', kind: 'dataset', version: 'v1',
    target_path: '/data/share/datasets/managed/test/v1', curation_status: 'team_card_pending', file_count: 2, total_bytes: 1024 }] });
  check(node("ingestion-published").innerHTML.includes("团队说明待完善"));
  check(!node("ingestion-published").innerHTML.includes("<script>"));
  check(node("ingestion-published").innerHTML.includes("/data/share/datasets/managed/test/v1"));

  subject.state.authEnabled = true;
  subject.state.authenticated = true;
  subject.updateAgentCode();
  check(node("ingestion-agent-code").textContent.includes("Authorization: Bearer $DATA_CENTER_TOKEN"));
  check(node("ingestion-agent-code").textContent.includes(origin + "/api/ingestion/status"));
  subject.clearCatalog();
  check(subject.state.ingestion === null);
  check(node("ingestion-jobs").innerHTML === "");
  check(node("ingestion-counts").innerHTML === "");
  check(node("ingestion-published").innerHTML === "");

  const requests = [];
  context.fetch = async (url, options) => {
    requests.push({ url, options });
    return { ok: true, status: 200, json: async () => ({ mode: "disabled", jobs: [], counts: {} }) };
  };
  await subject.loadIngestion();
  check(requests[0].url === "/api/ingestion/status");
  check(!requests[0].options.method || requests[0].options.method === "GET");
  check(requests[1].url === "/api/ingestion/published");
  check(node("ingestion-mode").dataset.mode === "disabled");
  check(node("ingestion-refresh").disabled === false);

  context.fetch = async () => ({ ok: false, status: 503, json: async () => ({ error: { message: "/private/path" } }) });
  await subject.loadIngestion();
  check(node("ingestion-mode").dataset.mode === "unavailable");
  check(!node("ingestion-state-description").textContent.includes("/private"));
  context.fetch = async () => ({ ok: false, status: 401, json: async () => ({ error: { code: "unauthenticated" } }) });
  await subject.loadIngestion();
  check(subject.state.authenticated === false);
  check(node("ingestion-jobs").innerHTML === "");
  check(node("auth-dialog").open);

  subject.state.authEnabled = false;
  subject.state.authenticated = true;
  const deliveries = [];
  context.fetch = () => new Promise((resolve) => { deliveries.push(resolve); });
  const pending = subject.loadIngestion();
  subject.showAuth();
  for (const deliver of deliveries) deliver({ ok: true, status: 200, json: async () => ({ mode: "active", jobs: [{ id: "late-private", status: "published" }] }) });
  await pending;
  check(node("ingestion-jobs").innerHTML === "");
  check(subject.state.ingestion === null);
  console.log(`Ingestion UI: ${checks} assertions passed.`);
})().catch((error) => { console.error(error); process.exitCode = 1; });
