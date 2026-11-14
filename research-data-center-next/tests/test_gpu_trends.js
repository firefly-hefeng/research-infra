"use strict";
// Monitoring must never turn stale, duplicate, or absent observations into activity.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const context = {window: {}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, "../static/gpu-trends.js"), "utf8"), context);
const {memoryPercent, createHistory, segments} = context.window.HubMetrics;
const now = Date.parse("2026-11-14T08:00:00Z");
const gpu = {index: 0, utilization_percent: 0, memory_used_bytes: 8 * 1024 ** 3, memory_total_bytes: 32 * 1024 ** 3};
const server = {id: "machine-a", status: "online", stale: false, observed_at: new Date(now).toISOString(), gpus: [gpu]};
const history = createHistory(3);
const record = (item = server, at = now) => history.record({servers: [item], stale_after_seconds: 300}, at);
assert.equal(memoryPercent(gpu), 25);
assert.equal(memoryPercent({...gpu, memory_used_bytes: 0}), 0);
for (const missing of [null, undefined, "8", -1, Infinity]) {
  assert.equal(memoryPercent({...gpu, memory_used_bytes: missing}), null);
}
assert.equal(memoryPercent({...gpu, memory_total_bytes: 0}), null);
assert.equal(memoryPercent({...gpu, memory_used_bytes: gpu.memory_total_bytes + 1}), null);
for (const override of [{stale:true}, {stale:undefined}, {status:"unreachable"}, {status:"not_configured"}, {observed_at:"invalid"}, {observed_at:new Date(now-301000).toISOString()}, {observed_at:new Date(now+31000).toISOString()}]) record({...server, ...override});
assert.equal(history.points(server, gpu).length, 0);
record(); record(); record();
assert.equal(history.points(server, gpu).length, 1, "repeated snapshot is one observation");
assert.equal(history.points(server, gpu)[0].utilization, 0, "observed zero is a real value");
record({...server, observed_at:new Date(now-1000).toISOString()});
assert.equal(history.points(server, gpu).length, 1, "backward timestamps never append");
for (let index = 1; index <= 4; index++) {
  record({...server, observed_at:new Date(now+index*60000).toISOString(), gpus:[{...gpu, utilization_percent:index === 3 ? null : index*10}]}, now+index*60000);
}
const points = history.points(server, gpu);
assert.equal(points.length, 3, "session history is bounded");
assert.equal(points[1].utilization, null, "missing utilization must not become zero");
assert.equal(segments(points, "utilization").length, 2, "missing samples break the curve");
assert.equal(segments(points, "memory").length, 1);
assert.equal(segments([{time:0, memory:0}, {time:181000, memory:50}], "memory").length, 2, "collection gaps break the curve");
assert.equal(history.points({...server, id:"machine-b"}, gpu).length, 0, "machines remain isolated");
assert.equal(history.points(server, {...gpu,index:1}).length, 0, "GPUs remain isolated");
record({...server, stale:true, observed_at:new Date(now+500000).toISOString()}, now+500000);
assert.equal(history.points(server, gpu).at(-1).time, now+240000, "stale refresh cannot extend history");
history.clear();
assert.equal(history.points(server, gpu).length, 0);
console.log("GPU trends: missing values, stale/duplicate observations, isolation, retention and gaps passed.");
