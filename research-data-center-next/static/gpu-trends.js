/* Browser-session observations only. No synthetic or persisted monitoring data. */
"use strict";
(() => {
  const number = value => typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
  const percent = value => number(value) !== null && value <= 100 ? value : null;
  function memoryPercent(gpu) {
    const used = number(gpu.memory_used_bytes), total = number(gpu.memory_total_bytes);
    return used !== null && total > 0 && used <= total ? used / total * 100 : null;
  }
  function createHistory(limit = 120) {
    const records = new Map();
    const key = (server, gpu) => `${server.id}/${gpu.uuid || gpu.index}`;
    return {
      record(data, now = Date.now()) {
        for (const server of data?.servers || []) {
          const time = Date.parse(server.last_success_at || server.observed_at);
          const maxAge = (number(data.stale_after_seconds) || 300) * 1000;
          if (server.stale !== false || !["online", "partial"].includes(server.status) || !Number.isFinite(time) || time > now + 30000 || now - time > maxAge) continue;
          for (const gpu of server.gpus || []) {
            const id = key(server, gpu), points = records.get(id) || [];
            if (points.length && time <= points[points.length - 1].time) continue;
            points.push({time, utilization: percent(gpu.utilization_percent), memory: memoryPercent(gpu)});
            records.set(id, points.slice(-limit));
          }
        }
      },
      points(server, gpu) { return records.get(key(server, gpu)) || []; },
      clear() { records.clear(); },
    };
  }
  // A gap in observations remains a gap, including missing metric values.
  function segments(points, field, maxGap = 180000) {
    const groups = []; let current = [], previous = null;
    for (const point of points) {
      const valid = percent(point[field]) !== null;
      if (!valid || (previous !== null && point.time - previous > maxGap)) {
        if (current.length) groups.push(current);
        current = [];
      }
      if (valid) current.push(point);
      previous = point.time;
    }
    if (current.length) groups.push(current);
    return groups;
  }
  window.HubMetrics = {number, percent, memoryPercent, createHistory, segments};
})();
