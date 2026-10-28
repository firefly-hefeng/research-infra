"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const kinds = {
    dataset: { label: "数据区记录", icon: "database" },
    model: { label: "模型区记录", icon: "model" },
    feature: { label: "特征", icon: "feature" },
    annotation: { label: "标注", icon: "tag" },
    collection: { label: "资源集合", icon: "layers" },
    artifact: { label: "研究产物", icon: "file" },
  };
  const statuses = {
    verified: "rmp 入口可读",
    documented: "文档已收录",
    partial: "部分核验",
    missing: "路径未找到",
    restricted: "rmp 访问受限",
  };
  const statusExplanations = {
    verified: "已保存的观察证据表明 rmp 当时可读取此目录入口，不代表所有后代文件可读。存在性、内容完整性、模型可运行性和使用许可分别记录。",
    documented: "该资源已从既有文档登记。本次可能尚未连接对应服务器，请以来源记录和核验时间判断时效性。",
    partial: "该条目仅完成部分核验。具体已确认项、未知项和限制见下方备注与元数据。",
    missing: "在本次核验所用服务器与路径下未找到该资源。可能涉及路径变更、迁移或来源过期，使用前需联系资源负责人。",
    restricted: "资源的访问权限受限。目录可见不代表当前账号可以读取原始内容，需联系资源负责人获取授权。",
  };
  const state = {
    summary: null, page: 1, pageSize: 30, total: 0, items: [],
    query: { q: "", kind: "", server: "", status: "", category: "" },
    assetController: null, detailController: null, refreshController: null,
    authEnabled: false, authenticated: false, toastTimer: null, searchTimer: null,
    drawerTrigger: null, loading: false,
    mapping: null, mappingIndex: new Map(), mappingController: null,
    resourceView: "cards", resourceGroup: "", resourceQuery: "", resourceGap: "", resourceTopic: "",
    guide: null, ingestion: null, ingestionController: null,
    platform: "home", servers: null, serversController: null,
    platformReady: false, serversPollTimer: null,
    literature: null, literatureController: null, literaturePage: 1,
    literatureQuery: { q: "", category: "", domain: "" },
    resourcePage: 1, resourcePageSize: 12, resourceFiltered: [], resourceSearchTimer: null,
    mapRenderedFor: null, mapPreview: "", animations: new Set(),
  };
  const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const icon = (name, className = "") => `<svg class="icon ${escape(className)}" aria-hidden="true"><use href="#i-${escape(name)}"/></svg>`;
  const number = (value) => value === null || value === undefined || value === "" ? "—" : Number(value).toLocaleString("zh-CN");
  const known = (value) => value !== null && value !== undefined && value !== "";
  const stringValue = (value) => !known(value) ? "未记录" : typeof value === "object" ? JSON.stringify(value, null, 2) : String(value);
  const kindInfo = (key) => kinds[key] || { label: key || "未分类", icon: "file" };
  const kindClass = (key) => Object.hasOwn(kinds, key) ? key : "artifact";
  const statusClass = (key) => Object.hasOwn(statuses, key) ? key : "documented";
  const statusBadge = (key) => `<span class="status-badge ${statusClass(key)}">${escape(statuses[key] || key || "未记录")}</span>`;
  const kindBadge = (key) => `<span class="kind-badge ${kindClass(key)}">${escape(kindInfo(key).label)}</span>`;
  const subtypeLabels = { dataset: "数据记录", model_weights: "模型权重", directory_collection: "待细分目录集合", collection: "资料集合", feature: "派生特征", annotation: "标注资料", artifact: "研究工件" };
  const subtypeText = (key) => subtypeLabels[key] || key || "类型待补充";
  const mappingFor = (id) => state.mappingIndex.get(id);
  const researchFor = (item) => item?.documentation?.research || {};
  const textList = (value) => Array.isArray(value) ? value.filter((entry) => typeof entry === "string" && entry.trim()) : [];
  const topicFor = (id) => state.guide?.categories?.find((entry) => entry.id === id);
  const researchSummary = (item) => item?.documentation?.summary || researchFor(item).summary || item?.description || "用途说明待补充";
  const versionText = (item) => item?.version_state === "unconfirmed" || !item?.version?.release_id ? "版本未固定" : item.version.release_id;
  const mappingAccessText = (item) => item?.checks?.access === "readable" ? "rmp 入口可读" : item?.checks?.access === "restricted" ? "rmp 访问受限" : "访问状态未知";
  const dateText = (value, includeTime = false) => {
    if (!value) return "未记录";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit", ...(includeTime ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}) }).format(date);
  };
  const sizeText = (value) => {
    if (!known(value) || !Number.isFinite(Number(value)) || Number(value) < 0) return "未记录";
    let size = Number(value), unit = 0;
    const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
    while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
    return `${size.toLocaleString("zh-CN", { maximumFractionDigits: unit ? 2 : 0 })} ${units[unit]}`;
  };
  const safeURL = (value) => {
    try {
      const url = new URL(value, window.location.origin);
      return ["http:", "https:"].includes(url.protocol) ? url.href : null;
    } catch { return null; }
  };

  const migrationLabels = { planned: "计划迁移", copying: "复制中 · 尚未切换", verified: "已校验 · 尚未切换", switched: "已核验切换", blocked: "迁移受阻", rolled_back: "已回退" };
  const ingestionModes = {
    "not-configured": { label: "接收服务未配置", description: "本门户尚未连接增补状态库。可先阅读指南和准备说明，接收权限与部署状态请向管理团队确认。" },
    planned: { label: "规则 worker 待启动", description: "状态库已就绪，尚无 worker 活动记录。提交登记与后续处理以管理团队启用情况为准。" },
    disabled: { label: "规则 worker 已停用", description: "已明确停用规则处理。现有状态仅供查阅，页面不会恢复或启动 worker。" },
    active: { label: "规则 worker 近期活跃", description: "最近有规则处理活动。以下为已登记任务的观察快照；提交不等于审核通过或已经发布。" },
    "worker-stale": { label: "worker 心跳已过期", description: "最近一次活动已超出心跳时限。保留上次任务状态，请管理团队检查；页面不会自动重启处理。" },
    unavailable: { label: "运行状态暂不可用", description: "无法取得可信的处理快照。请稍后刷新；不据此判断提交成功、失败或 worker 正在运行。" },
  };
  const ingestionStatuses = { submitted: "待核验", validating: "核验中", needs_information: "待补充说明", review_required: "待管理审核", ready: "已审待发布", publishing: "发布中", published: "已发布", failed: "处理失败" };

  const metricValue = (value) => typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
  const percentText = (value) => metricValue(value) !== null && value <= 100 ? `${value.toLocaleString("zh-CN", { maximumFractionDigits: 1 })}%` : "—";
  const metricBar = (value, label) => metricValue(value) !== null && value <= 100 ? `<progress class="metric-bar" max="100" value="${value}" aria-label="${escape(label)} ${percentText(value)}"></progress>` : '<span class="metric-bar metric-unknown" aria-hidden="true"></span>';

  function selectPlatform(value) {
    const dataAnchors = ["data", "data-platform", "research-guide", "resources", "catalog", "ingestion", "ingestion-queue", "ingestion-admin", "agent", "storage-status"];
    const current = ["servers", "literature"].includes(value) ? value : dataAnchors.includes(value) ? "data-platform" : "home";
    state.platform = current;
    for (const id of ["servers", "literature", "data-platform"]) $(id).hidden = id !== current;
    for (const id of ["overview", "platform-launchers", "home-guide"]) $(id).hidden = current !== "home";
    $("platform-back").hidden = current === "home";
    $("data-navigation").hidden = current !== "data-platform";
    $("workspace-label").textContent = { home: "首页", servers: "服务器资源", literature: "资源参考", "data-platform": "数据管理" }[current];
    document.querySelectorAll("[data-platform-link]").forEach((link) => {
      const active = link.dataset.platformLink === current;
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
    });
    scheduleServerRefresh(true);
  }

  function scheduleServerRefresh(immediate = false) {
    clearTimeout(state.serversPollTimer);
    state.serversPollTimer = null;
    if (!state.platformReady || state.platform !== "servers" || document.visibilityState !== "visible" || (state.authEnabled && !state.authenticated)) return;
    if (immediate && !$("servers-refresh").disabled) loadServers();
    state.serversPollTimer = setTimeout(() => {
      if (state.platform === "servers" && document.visibilityState === "visible" && !$("servers-refresh").disabled) loadServers();
      scheduleServerRefresh();
    }, 60000);
  }

  function renderServers(data) {
    state.servers = data;
    const servers = Array.isArray(data?.servers) ? data.servers.slice(0, 12) : [];
    const validStatuses = { online: "观测在线", partial: "部分指标可读", unreachable: "当前不可达", not_configured: "未配置采集" };
    $("servers-observed").textContent = data?.mode === "not_configured" ? "服务器采集尚未配置，暂无可用的观察数据。" : `${data?.generated_at ? `快照生成 ${dateText(data.generated_at, true)}` : "尚无采集时间"}${data?.served_at ? ` · 读取 ${dateText(data.served_at, true)}` : ""} · 此页可见时每分钟更新已保存快照`;
    $("compute-launcher-status").textContent = data?.mode === "not_configured" ? "采集尚未配置" : `${number(servers.length)} 台机器 · 观察快照`;
    $("servers-grid").innerHTML = servers.length ? servers.map((server) => {
      const status = Object.hasOwn(validStatuses, server.status) ? server.status : "not_configured";
      const old = server.stale === true || status === "unreachable";
      const time = server.last_success_at || server.observed_at;
      const gpus = Array.isArray(server.gpus) ? server.gpus.slice(0, 32) : null;
      const disks = Array.isArray(server.disks) ? server.disks.slice(0, 20) : [];
      const cpu = server.cpu || {}, memory = server.memory || {};
      const observed = old ? (time ? `以下保留上次观测值：${dateText(time, true)}。不代表当前负载。` : "本次未取得可信指标，也没有此前成功观察。") : `指标观察：${dateText(time, true)}`;
      return `<article class="server-card"><div class="server-card-heading"><span class="platform-number">COMPUTE / ${escape(server.id || "")}</span><span class="server-status" data-status="${old ? "stale" : status}">${escape(status === "unreachable" ? "当前不可达" : server.stale ? "快照已过期" : validStatuses[status])}</span></div><h3>${escape(server.name || "未命名机器")}</h3><code class="server-address">${escape(server.address || "地址未记录")}</code><p class="server-observed${old ? " is-old" : ""}">${escape(observed)}</p><div class="server-metrics"><div><span>CPU 使用</span><strong>${percentText(cpu.usage_percent)}</strong>${metricBar(cpu.usage_percent, "CPU 使用") }<small>${number(metricValue(cpu.logical_cores))} 逻辑核 · 1 分钟负载 ${number(metricValue(cpu.load_1m))}</small></div><div><span>内存使用</span><strong>${percentText(memory.used_percent)}</strong>${metricBar(memory.used_percent, "内存使用")}<small>可用 ${escape(sizeText(memory.available_bytes))} / ${escape(sizeText(memory.total_bytes))}</small></div></div><div class="server-gpus"><h4>GPU <span>${gpus === null ? "未取得观察" : `${number(gpus.length)} 张已观察`}</span></h4>${gpus?.length ? `<p class="gpu-model">${escape([...new Set(gpus.map((gpu) => gpu.name).filter(Boolean))].join(" / ") || "型号未记录")}</p><div class="gpu-grid">${gpus.map((gpu) => `<div class="gpu-item"><div><span>GPU ${escape(gpu.index ?? "—")}</span><strong>${percentText(gpu.utilization_percent)}</strong></div>${metricBar(gpu.utilization_percent, `GPU ${gpu.index ?? ""} 使用`)}<small>显存 ${escape(sizeText(gpu.memory_used_bytes))}<br>共 ${escape(sizeText(gpu.memory_total_bytes))}</small></div>`).join("")}</div>` : `<p class="server-no-metric">${gpus === null ? "尚无 GPU 指标；不据此判断机器空闲。" : "本次采集未报告 GPU 设备。"}</p>`}</div><details class="server-detail"><summary>磁盘与观察详情 <span aria-hidden="true">＋</span></summary><div>${disks.length ? disks.map((disk) => `<div class="server-disk"><div><code>${escape(disk.mount || "挂载点未记录")}</code><strong>${disk.capacity_note === "object_storage_capacity_not_applicable" ? "对象存储" : percentText(disk.used_percent)}</strong></div>${disk.capacity_note === "object_storage_capacity_not_applicable" ? `<small>容量口径不适用 · ${escape(disk.filesystem || "对象存储挂载")}</small>` : `${metricBar(disk.used_percent, `${disk.mount || "磁盘"} 使用`)}<small>可用 ${escape(sizeText(disk.available_bytes))} / ${escape(sizeText(disk.total_bytes))}${disk.filesystem ? ` · ${escape(disk.filesystem)}` : ""}</small>`}</div>`).join("") : '<p>未取得磁盘观察。</p>'}<dl><div><dt>CPU 型号</dt><dd>${escape(cpu.model || "未记录")}</dd></div><div><dt>最近尝试</dt><dd>${escape(dateText(server.attempted_at, true))}</dd></div><div><dt>最近成功</dt><dd>${escape(dateText(time, true))}</dd></div>${server.remote_observed_at ? `<div><dt>远端时钟</dt><dd>${escape(dateText(server.remote_observed_at, true))}（仅供对照）</dd></div>` : ""}${server.error_code ? `<div><dt>观察结果</dt><dd>${escape(server.error_code)}</dd></div>` : ""}</dl></div></details></article>`;
    }).join("") : '<p class="platform-empty">尚无服务器观察记录。请先阅读使用说明，采集启用后将在这里展示。</p>';
  }

  async function loadServers(signal) {
    state.serversController?.abort();
    const controller = new AbortController();
    state.serversController = controller;
    const cancel = () => controller.abort();
    if (signal?.aborted) controller.abort();
    signal?.addEventListener("abort", cancel, { once: true });
    $("servers-refresh").disabled = true;
    try {
      const data = await api("/api/platform/servers", { signal: controller.signal });
      if (!controller.signal.aborted && (!state.authEnabled || state.authenticated)) renderServers(data);
    } catch (error) {
      if (error.name === "AbortError" || error.code === "unauthenticated" || controller.signal.aborted) return;
      state.servers = null;
      $("servers-observed").textContent = "服务器快照暂不可读取，请稍后重试。无法由此判断机器是否在线。";
      $("compute-launcher-status").textContent = "观察暂不可用";
      $("servers-grid").innerHTML = '<p class="platform-empty">暂未取得可信的服务器快照。点击“刷新快照”重试。</p>';
    } finally {
      signal?.removeEventListener("abort", cancel);
      if (state.serversController === controller) $("servers-refresh").disabled = false;
    }
  }

  function renderLiterature(data) {
    state.literature = data;
    const items = Array.isArray(data?.items) ? data.items.slice(0, 24) : [];
    const total = metricValue(data?.total) ?? 0;
    const categories = Array.isArray(data?.categories) ? data.categories : [];
    const domains = Array.isArray(data?.domains) ? data.domains : [];
    $("literature-category").innerHTML = '<option value="">全部类别</option>' + categories.map((entry) => `<option value="${escape(entry.id)}">${escape(entry.label)} · ${number(entry.count)}</option>`).join("");
    $("literature-domain").innerHTML = '<option value="">全部网站</option>' + domains.map((entry) => `<option value="${escape(entry.domain)}">${escape(entry.domain)} · ${number(entry.count)}</option>`).join("");
    $("literature-category").value = state.literatureQuery.category;
    $("literature-domain").value = state.literatureQuery.domain;
    $("literature-reset").hidden = !Object.values(state.literatureQuery).some(Boolean);
    $("literature-summary").textContent = `${number(total)} 条匹配来源 · 索引关联 ${number(data?.coverage?.resources)} 条资料记录`;
    $("literature-results").innerHTML = items.length ? items.map((item) => {
      const url = item.url ? safeURL(item.url) : null;
      const resources = Array.isArray(item.resources) ? item.resources : [];
      const labels = Array.isArray(item.categories) ? item.categories : [];
      const uses = [...new Set(resources.flatMap((resource) => textList(resource.uses)))].slice(0, 2);
      return `<article class="literature-card"><div class="literature-source"><span>已有参考来源</span><code>${escape(item.domain || "来源网站未记录")}</code></div><h3>${url ? `<a href="${escape(url)}" target="_blank" rel="noopener noreferrer">${escape(item.title || item.url)}${icon("external")}</a>` : escape(item.title || "参考名称待补充")}</h3>${uses.length ? `<p class="literature-uses">${uses.map(escape).join("；")}</p>` : ""}${labels.length ? `<div class="resource-task-labels">${labels.map((entry) => `<span>${escape(entry.label || entry.id)}</span>`).join("")}</div>` : ""}<div class="literature-resources"><span>关联资料 · ${number(resources.length)} 条</span><div>${resources.slice(0, 5).map((resource) => `<button type="button" data-literature-asset="${escape(resource.asset_id)}">${escape(resource.name || "查看关联资料")}${icon("arrow")}</button>`).join("")}</div>${resources.length > 5 ? `<details><summary>再看 ${number(resources.length - 5)} 条关联</summary><div>${resources.slice(5).map((resource) => `<button type="button" data-literature-asset="${escape(resource.asset_id)}">${escape(resource.name || "查看关联资料")}${icon("arrow")}</button>`).join("")}</div></details>` : ""}</div></article>`;
    }).join("") : '<div class="platform-empty"><h3>没有找到匹配来源</h3><p>试试更短的关键词，或清除类别与网站筛选。</p></div>';
    $("literature-results").setAttribute("aria-busy", "false");
    const pages = Math.max(1, Math.ceil(total / 24));
    $("literature-page-summary").textContent = total ? `显示 ${(state.literaturePage - 1) * 24 + 1}–${Math.min(state.literaturePage * 24, total)} 条，共 ${number(total)} 条` : "暂无匹配来源";
    $("literature-page-label").textContent = `${state.literaturePage} / ${pages}`;
    $("literature-prev").disabled = state.literaturePage <= 1;
    $("literature-next").disabled = state.literaturePage >= pages;
  }

  async function loadLiterature(signal) {
    state.literatureController?.abort();
    const controller = new AbortController();
    state.literatureController = controller;
    const cancel = () => controller.abort();
    if (signal?.aborted) controller.abort();
    signal?.addEventListener("abort", cancel, { once: true });
    $("literature-results").setAttribute("aria-busy", "true");
    $("literature-summary").textContent = "正在读取来源索引…";
    const query = new URLSearchParams({ ...state.literatureQuery, page: state.literaturePage, page_size: 24 });
    try {
      const data = await api(`/api/platform/literature?${query}`, { signal: controller.signal });
      if (!controller.signal.aborted && (!state.authEnabled || state.authenticated)) renderLiterature(data);
    } catch (error) {
      if (error.name === "AbortError" || error.code === "unauthenticated" || controller.signal.aborted) return;
      state.literature = null;
      $("literature-results").innerHTML = '<p class="platform-empty">来源索引暂不可用。请点击搜索重试；数据管理中的原资料说明仍可查看。</p>';
      $("literature-summary").textContent = "未能读取来源索引";
      $("literature-results").setAttribute("aria-busy", "false");
      $("literature-page-summary").textContent = "读取失败";
      $("literature-prev").disabled = true;
      $("literature-next").disabled = true;
    } finally { signal?.removeEventListener("abort", cancel); }
  }

  function renderIngestion(data) {
    state.ingestion = data;
    const mode = Object.hasOwn(ingestionModes, data?.mode) ? data.mode : "unavailable";
    const wording = ingestionModes[mode];
    $("ingestion-mode").dataset.mode = mode;
    $("ingestion-mode").textContent = wording.label;
    $("ingestion-state-description").textContent = wording.description;
    $("ingestion-observed").textContent = `${data?.observed_at ? `状态读取 ${dateText(data.observed_at, true)}` : "尚无状态观察时间"}${data?.worker?.last_heartbeat_at ? ` · 最近活动 ${dateText(data.worker.last_heartbeat_at, true)}` : ""}`;
    const counts = data?.counts;
    const sum = (...keys) => !counts ? null : keys.reduce((total, key) => total + (Number.isSafeInteger(counts[key]) && counts[key] >= 0 ? counts[key] : 0), 0);
    const metrics = [["待核验 / 核验中", sum("submitted", "validating")], ["待补充 / 待审核", sum("needs_information", "review_required")], ["待发布 / 发布中", sum("ready", "publishing")], ["已发布", sum("published")], ["处理失败", sum("failed")]];
    $("ingestion-counts").innerHTML = metrics.map(([label, value]) => `<div class="ingestion-count"><span>${label}</span><strong>${number(value)}</strong></div>`).join("");
    const jobs = Array.isArray(data?.jobs) ? data.jobs.filter((job) => job && Object.hasOwn(ingestionStatuses, job.status)).slice(0, 20) : [];
    $("ingestion-queue-limit").textContent = jobs.length ? `最近 ${number(jobs.length)} 项` : "只读状态";
    if (!jobs.length) {
      const message = mode === "unavailable" ? "状态读取失败，暂不显示队列内容。" : mode === "not-configured" ? "状态库未配置，暂无可展示的接收记录。" : "此快照尚无已登记提交。完成标记不等于 worker 已接手，后续以任务状态为准。";
      $("ingestion-jobs").innerHTML = `<p class="ingestion-empty">${message}</p>`;
      return;
    }
    $("ingestion-jobs").innerHTML = `<div class="ingestion-table-scroll"><table class="ingestion-table"><thead><tr><th scope="col">提交资料 / 编号</th><th scope="col">处理状态</th><th scope="col">最近更新</th></tr></thead><tbody>${jobs.map((job) => `<tr><td><strong>${escape(job.display_name || "未命名提交")}</strong><code>${escape(job.id)}</code><small>${job.kind ? escape(kindInfo(job.kind).label) : "类型待确认"}</small></td><td><span class="ingestion-job-status" data-status="${escape(job.status)}">${escape(ingestionStatuses[job.status])}</span>${job.reason_code ? `<small>原因代码：${escape(job.reason_code)}</small>` : ""}</td><td>${escape(dateText(job.updated_at, true))}<small>提交 ${escape(dateText(job.submitted_at, true))}</small></td></tr>`).join("")}</tbody></table></div>`;
  }

  function renderPublished(data) {
    const items = Array.isArray(data?.items) ? data.items.slice(0, 20) : [];
    if (!items.length) {
      $("ingestion-published").innerHTML = `<p class="ingestion-empty">${data?.unavailable ? "发布回执暂时无法读取。" : data?.configured ? "尚无可展示的正式发布回执。" : "状态库未配置，暂无新入库资源记录。"}</p>`;
      return;
    }
    $("ingestion-published").innerHTML = items.map((item) => `<article class="ingestion-publication"><div><span class="ingestion-job-status" data-status="published">已入库</span><span>${item.kind === "model" ? "模型" : "数据集"} · ${escape(item.version)}</span></div><h4>${escape(item.title || item.resource_id)}</h4><p>${item.curation_status === "team_card_pending" ? "团队说明待完善" : "正式资料卡登记状态待确认"}</p><code>${escape(item.target_path)}</code><small>${number(item.file_count)} 个文件 · ${escape(sizeText(item.total_bytes))} · 发布于 ${escape(dateText(item.published_at, true))}</small></article>`).join("");
  }

  async function loadIngestion(signal) {
    state.ingestionController?.abort();
    const controller = new AbortController();
    state.ingestionController = controller;
    if (signal?.aborted) controller.abort();
    const cancel = () => controller.abort();
    signal?.addEventListener("abort", cancel, { once: true });
    $("ingestion-refresh").disabled = true;
    try {
      await Promise.allSettled([
        api("/api/ingestion/status", { signal: controller.signal }).then((data) => {
          if (!controller.signal.aborted && (!state.authEnabled || state.authenticated)) renderIngestion(data);
        }).catch((error) => {
          if (error.name !== "AbortError" && error.code !== "unauthenticated" && !controller.signal.aborted) renderIngestion({ mode: "unavailable" });
        }),
        api("/api/ingestion/published", { signal: controller.signal }).then((data) => {
          if (!controller.signal.aborted && (!state.authEnabled || state.authenticated)) renderPublished(data);
        }).catch((error) => {
          if (error.name !== "AbortError" && error.code !== "unauthenticated" && !controller.signal.aborted) renderPublished({ unavailable: true });
        }),
      ]);
    } catch (error) {
      if (error.name !== "AbortError" && error.code !== "unauthenticated" && !controller.signal.aborted) renderIngestion({ mode: "unavailable" });
    } finally {
      signal?.removeEventListener("abort", cancel);
      if (state.ingestionController === controller) $("ingestion-refresh").disabled = false;
    }
  }

  function storageInfo(item, asset) {
    const storage = item?.storage || asset?.storage || null;
    const migration = storage?.migration || {};
    const active = migration.state === "switched" && migration.activated === true;
    // Only the explicit activated receipt can promote a target to the current path.
    const registered = item?.current_path || asset?.path || item?.path || "";
    const current = active ? storage.canonical_path || registered : storage?.historical?.path || registered;
    const aliases = active && Array.isArray(storage?.legacy_aliases) ? storage.legacy_aliases.filter((alias) => alias?.path) : [];
    const phase = migration.state === "switched" && !active ? "切换回执待确认" : migrationLabels[migration.state] || (migration.state ? `状态：${migration.state}` : "未提供迁移清单");
    return { storage, migration, active, current, aliases, phase,
      planned: storage?.planned_path && storage.planned_path !== current ? storage.planned_path : "" };
  }

  function migrationBadge(info) {
    const tone = info.active ? "is-switched" : info.migration.state === "blocked" ? "is-blocked" : !info.storage ? "is-unknown" : "";
    return `<span class="migration-badge ${tone}">${escape(info.phase)}</span>`;
  }

  function locationSearchTerms(item) {
    const info = storageInfo(item);
    return [info.current, info.planned, info.storage?.historical?.path, ...info.aliases.flatMap((alias) => [alias.path, alias.target])].filter(Boolean);
  }

  const physicalFor = (item, asset) => item?.physical_inventory || asset?.physical_inventory || null;
  const physicalOverview = () => state.summary?.scope?.physical_inventory || state.mapping?.physical_inventory || null;
  const extensionLabel = (name) => name === "[no extension]" ? "无扩展名" : name === "[other extension]" ? "其他扩展名" : name;

  function physicalDependencyNote(stats, className = "physical-dependency") {
    if (!known(stats?.external_absolute_symlink_count) || Number(stats.external_absolute_symlink_count) <= 0) return "";
    return `<p class="${className}"><strong>${number(stats.external_absolute_symlink_count)} 个域外绝对链接</strong>是历史路径依赖，未追随其内容迁入。此计数不代表目标全部可用或已经丢失。</p>`;
  }

  function renderPhysicalSummary() {
    const target = $("physical-summary");
    const physical = physicalOverview();
    const stats = physical?.totals;
    target.hidden = !stats;
    if (!stats) { target.replaceChildren(); return; }
    const metrics = [
      ["普通文件", number(stats.file_count), "按文件路径计数，硬链接可有多个入口"],
      ["目录", number(stats.directory_count), "源根下目录，不含公共根自身"],
      ["符号链接", number(stats.symlink_count), "不跟随链接目标计数"],
      ["普通文件去重体积", sizeText(stats.unique_file_bytes), known(stats.unique_file_bytes) ? `${number(stats.unique_file_bytes)} 字节 · 按源文件系统 dev / ino 去重` : "尚未记录"],
    ];
    target.innerHTML = `<div class="physical-summary-heading"><span>源目录实测清点</span><span>采集 ${escape(dateText(physical.observed_at, true))} · 非实时</span></div><div class="physical-metric-grid">${metrics.map(([label, value, note]) => `<div class="physical-metric" title="${escape(note)}"><span>${escape(label)}</span><strong>${escape(value)}</strong></div>`).join("")}</div><p class="physical-summary-note">直接汇总两个源公共根，不由目录卡片相加；体积不是 CPFS 占用或迁移完成量。</p>${physicalDependencyNote(stats)}${Number(stats.inode_observation_conflicts) > 0 ? `<p class="physical-dependency">${number(stats.inode_observation_conflicts)} 项 inode 观察存在差异，体积不能解释为一致时点精确值。</p>` : ""}`;
  }

  function physicalCompact(item) {
    const physical = physicalFor(item);
    if (!physical) return "";
    if (physical.entry_observed === false) return '<p class="resource-physical">源清点 · 此入口未在清单中观察到</p>';
    return `<p class="resource-physical" title="采集 ${escape(dateText(physical.observed_at, true))}；递归普通文件，不跟随链接，不代表样本数"><span>源清点</span>${number(physical.file_count)} 个文件 <span aria-hidden="true">·</span> ${escape(sizeText(physical.unique_file_bytes))}<span>去重</span></p>`;
  }

  function physicalDetail(item, asset) {
    const physical = physicalFor(item, asset);
    if (!physical) return "";
    const field = (label, value) => `<div><dt>${escape(label)}</dt><dd>${escape(value)}</dd></div>`;
    const extensions = Object.entries(physical.extension_counts || {}).filter(([, count]) => known(count) && Number.isFinite(Number(count)) && Number(count) >= 0).sort((a, b) => Number(b[1]) - Number(a[1])).slice(0, 12);
    const max = Math.max(1, ...extensions.map(([, count]) => Number(count)));
    const extensionHTML = extensions.length ? `<details class="physical-extensions"><summary>文件扩展名构成 · 前 ${extensions.length} 类</summary><p>按普通文件路径计数；扩展名不等于研究样本、有效格式或新资源身份。</p><ul>${extensions.map(([name, count]) => `<li><div><code>${escape(extensionLabel(name))}</code><span>${number(count)}</span></div><progress value="${Number(count)}" max="${max}" aria-label="${escape(extensionLabel(name))}，${number(count)} 个普通文件"></progress></li>`).join("")}</ul></details>` : "";
    return `<section id="detail-physical" class="drawer-section physical-detail"><h3>${icon("database")}本次源目录物理清点</h3><p class="physical-observation">采集：${escape(dateText(physical.observed_at, true))} · ${physical.location_role === "pre_migration_source" ? "迁移前源位置" : "源清单观察"}</p>${physical.observed_path ? `<p class="physical-observed-path"><code>${escape(physical.observed_path)}</code></p>` : ""}${physical.entry_observed === false ? '<p class="status-explanation">本次清单未直接观察到这个登记入口。未知统计保持空缺，不按空目录处理。</p>' : ""}<dl class="physical-detail-grid">${field("递归普通文件", number(physical.file_count))}${field("后代目录", number(physical.directory_count))}${field("符号链接", number(physical.symlink_count))}${field("唯一 inode（全部类型）", number(physical.unique_inodes))}${field("按文件路径累加体积", sizeText(physical.apparent_file_bytes))}${field("去重普通文件体积", sizeText(physical.unique_file_bytes))}${field("源文件分配块体积", sizeText(physical.allocated_file_bytes))}${field("唯一普通文件 inode", number(physical.unique_file_inodes))}</dl><p class="drawer-note">仅统计入口的严格后代，入口自身不计入；不跟随符号链接。容量反映源文件系统清点，不是 CPFS 占用预测，也不代表迁移完成。文件数不是研究样本数。</p>${physical.catalog_record_count > 1 ? `<p class="drawer-note">${number(physical.catalog_record_count)} 条登记说明共用此路径及同一份物理统计，不能重复相加。</p>` : ""}${physicalDependencyNote(physical)}${Number(physical.inode_observation_conflicts) > 0 ? `<p class="physical-dependency">${number(physical.inode_observation_conflicts)} 项 inode 的大小或分配块观察有差异；以下去重值保留首次观察，不能作为一致时点精确体积。</p>` : ""}${extensionHTML}<details class="physical-evidence"><summary>时间、来源与统计边界</summary><dl class="detail-grid">${field("后代最新修改时间（非采集时间）", dateText(physical.newest_mtime, true))}${field("来源", physical.source === "source_manifest" ? "源文件清单" : physical.source || "未记录")}${field("清点证据", physical.evidence_ref || "未记录")}</dl><p class="drawer-note">历史台账数量与本次递归清点来自不同时间和统计范围，分别保留，不相互覆盖。嵌套目录会重复覆盖，不能跨条目求和；清单也不等于原子文件系统快照。</p></details></section>`;
  }

  function updateObservationLabel() {
    const observed = (state.mapping?.items || []).map((item) => item.checks?.observed_at).filter((value) => value && Number.isFinite(Date.parse(value))).sort((a, b) => Date.parse(b) - Date.parse(a));
    $("updated-label").textContent = observed.length ? `最近入口观察 ${dateText(observed[0], true)} · 非实时` : `目录生成 ${dateText(state.summary?.generated_at || state.summary?.imported_at, true)} · 观察时间见条目`;
  }

  function storageObservation(entry) {
    const existence = entry.exists === true ? "存在" : entry.exists === false ? "未找到" : "存在性未知";
    const access = entry.readable === true ? "入口可读" : entry.readable === false ? "入口不可读" : "可读性未知";
    const mount = entry.mount || {};
    return `<li><strong>${escape(entry.host || "主机未记录")}</strong><p>${escape(entry.path || "位置未记录")}</p><p>${escape(entry.account || "账号未记录")} · ${existence} · ${access}</p>${mount.target || mount.fstype ? `<p>挂载：${escape(mount.target || "未记录")} · ${escape(mount.fstype || "类型未记录")}${mount.source ? ` · ${escape(mount.source)}` : ""}</p>` : ""}<span class="storage-observed">观察：${escape(dateText(entry.observed_at, true))}${entry.evidence_ref ? ` · 证据 ${escape(entry.evidence_ref)}` : ""}</span></li>`;
  }

  function renderStorageStatus() {
    renderPhysicalSummary();
    const items = state.mapping?.items || [];
    const scope = state.summary?.scope && typeof state.summary.scope === "object" ? state.summary.scope : {};
    const roots = scope.canonical_roots || {};
    const planRoots = scope.planned_roots || {};
    const registered = items.filter((item) => item.storage);
    const activated = registered.filter((item) => storageInfo(item).active);
    const phaseCounts = new Map();
    registered.forEach((item) => { const phase = storageInfo(item).phase; phaseCounts.set(phase, (phaseCounts.get(phase) || 0) + 1); });
    $("storage-summary").textContent = registered.length ? `${number(activated.length)} / ${number(items.length)} 条登记记录已核验切换 · ${Array.from(phaseCounts).map(([phase, count]) => `${phase} ${number(count)} 条`).join("；")}` : state.mapping ? "尚无逐项迁移核验清单 · 当前显示已登记位置，不能据此判断 CPFS 迁移已完成。" : "资料映射尚未载入 · 当前位置与切换结果待清单确认。";
    const globalMigration = scope.storage_migration;
    const rootCards = ["datasets", "models"].map((root) => {
      const members = items.filter((item) => (item.storage?.logical_root || (item.kind === "model" ? "models" : "datasets")) === root);
      const storages = members.filter((item) => item.storage);
      const currentRoot = typeof roots[root] === "string" ? roots[root] : storages.some((item) => storageInfo(item).active) ? "当前位置见逐条记录" : `/data/${root}`;
      const rootPhase = storages.length ? `${number(storages.filter((item) => storageInfo(item).active).length)} / ${number(members.length)} 条已核验切换` : "当前登记根 · 切换情况待清单确认";
      const hero = $(`domain-${root}-path`);
      if (hero) hero.textContent = currentRoot;
      return `<article class="storage-root-card"><div class="storage-root-top"><h3>${root === "models" ? "模型公共库" : "数据公共库"}</h3><span class="migration-badge ${storages.length && storages.every((item) => storageInfo(item).active) ? "is-switched" : "is-unknown"}">${escape(rootPhase)}</span></div><span class="storage-label">当前登记根</span><code>${escape(currentRoot)}</code>${planRoots[root] && planRoots[root] !== currentRoot ? `<span class="storage-label">计划目标 · 不表示已可用</span><code>${escape(planRoots[root])}</code>` : ""}<p>${number(state.mapping ? members.length : null)} 条登记记录。兼容路径与各主机访问结果见资料详情。</p></article>`;
    }).join("");
    const observed = registered.flatMap((item) => Array.isArray(item.storage.observations) ? item.storage.observations : []);
    const hosts = new Map();
    for (const entry of observed) {
      const root = entry.mount?.target || "挂载点未记录";
      const key = `${entry.host || "主机未记录"}\u0000${root}`;
      const prior = hosts.get(key);
      if (!prior || Date.parse(entry.observed_at || "") > Date.parse(prior.observed_at || "")) hosts.set(key, entry);
    }
    const hostHTML = hosts.size ? `<details class="storage-evidence"><summary>已记录的目标位置观察 · ${number(hosts.size)} 组主机 / 挂载点</summary><p class="storage-note">每组展示最新的一条入口观察，不代表整台主机或全部资料可读。未列出主机表示尚无证据，不能据此宣称三台服务器均已就绪。</p><ul class="storage-hosts">${Array.from(hosts.values()).map(storageObservation).join("")}</ul></details>` : '<p class="storage-note">暂未提供 CPFS 目标位置的主机观察；不将历史本地目录的可读状态用于新位置。</p>';
    $("storage-content").innerHTML = `<div class="storage-root-grid">${rootCards}</div>${globalMigration?.state ? `<p class="storage-note">迁移批次：${escape(globalMigration.migration_id || "未记录")} · ${escape(globalMigration.state === "switched" && globalMigration.activated !== true ? "切换回执待确认" : migrationLabels[globalMigration.state] || globalMigration.state)}${globalMigration.cutover_at ? ` · 切换回执时间 ${escape(dateText(globalMigration.cutover_at, true))}` : ""}</p>` : ""}${hostHTML}<p class="storage-note">CPFS 共享目标面向三台科研服务器；同一份共享资料只计一份登记身份。页面不执行复制、切换或上传。目标目录存在、复制完成或旧路径为符号链接，都不单独等于迁移已核验完成。</p><p class="storage-note">目录生成：${escape(dateText(state.mapping?.generated_at || state.summary?.generated_at, true))}。位置观察、历史登记与容量来源各自保留时间；不同条目的快照可能不同步。</p><div class="storage-actions"><a class="text-link" href="/docs/cpfs-team-guide.html">共享存储使用说明 ${icon("arrow")}</a><a class="text-link" href="/docs/standards.html">资料规范 ${icon("arrow")}</a></div>`;
  }

  function storageDetail(item, asset) {
    const info = storageInfo(item, asset);
    const storage = info.storage;
    const aliasHTML = info.aliases.map((alias, index) => `<div class="storage-alias"><strong>兼容路径 · ${escape(alias.kind === "symlink" ? "符号链接" : alias.kind || "类型未记录")}</strong><div class="path-box"><code>${escape(alias.path)}</code><button type="button" class="icon-button" data-copy-location="${escape(alias.path)}" aria-label="复制兼容路径 ${index + 1}">${icon("copy")}</button></div><p>目标：<code>${escape(alias.target || "未记录")}</code></p><p>${escape(alias.host || "主机未记录")} · ${escape(alias.state === "verified" ? "已核验" : alias.state || "状态未记录")} · ${escape(dateText(alias.verified_at, true))}</p></div>`).join("");
    const targetHTML = info.planned ? `<div class="storage-target"><strong>计划目标 · 尚未作为当前位置</strong><code>${escape(info.planned)}</code><p>以迁移清单的明确切换回执为准；不要将此路径直接替换到运行任务。</p></div>` : "";
    const observations = Array.isArray(storage?.observations) ? storage.observations : [];
    const observationHTML = observations.length ? `<details class="storage-evidence"><summary>${info.active ? "切换后位置观察" : "目标位置观察 · 不代表已切换"} · ${number(observations.length)} 项</summary><ul class="storage-hosts">${observations.map(storageObservation).join("")}</ul></details>` : "";
    const historical = storage?.historical;
    const historyHTML = historical ? `<details class="storage-history"><summary>历史登记与迁移证据</summary><ul><li>历史路径：<code>${escape(historical.path || "未记录")}</code></li><li>原位置观察：${escape(dateText(historical.observed_at, true))}</li><li>数量来源观察：${escape(dateText(historical.quantity_observed_at, true))}</li><li>迁移批次：${escape(info.migration.migration_id || "未记录")}</li><li>切换时间：${escape(dateText(info.migration.cutover_at, true))}</li><li>核验依据：${escape(info.migration.verification_ref || "未记录")}</li></ul><p class="drawer-note">历史位置的访问状态与容量不能作为新位置完整性或实时可读性的证明。</p></details>` : "";
    return `${storage ? `<p>${migrationBadge(info)}</p>` : '<p class="drawer-note">此条目尚未提供迁移核验清单；以下是已登记位置。</p>'}<span class="storage-label">${info.active ? "当前存储位置 · 已核验切换" : "当前登记位置"}</span><div class="path-box"><code id="asset-path">${escape(info.current || "路径未记录")}</code><button type="button" class="icon-button" id="copy-path" aria-label="复制当前完整路径" ${!info.current ? "disabled" : ""}>${icon("copy")}</button></div>${aliasHTML}${targetHTML}${observationHTML}${historyHTML}<p class="drawer-note">读取资料需要对应服务器的挂载、账号与文件权限。兼容路径只代表所列主机在所列时间的核验结果。</p>`;
  }

  function stopAnimations() {
    for (const animation of state.animations) animation.cancel();
    state.animations.clear();
  }

  function reveal(elements) {
    if (motionPreference.matches || document.hidden) return;
    Array.from(elements).slice(0, 6).forEach((element, index) => {
      if (!element.animate) return;
      const animation = element.animate([{ opacity: 0.65 }, { opacity: 1 }], {
        duration: 180, delay: index * 25, easing: "ease-out", iterations: 1,
      });
      state.animations.add(animation);
      const done = () => state.animations.delete(animation);
      animation.onfinish = done;
      animation.oncancel = done;
    });
  }

  function focusResourceResults() {
    const target = $("resource-results-label");
    target.setAttribute("tabindex", "-1");
    target.focus({ preventScroll: true });
    target.scrollIntoView({ block: "center", behavior: motionPreference.matches ? "instant" : "smooth" });
  }

  // This is a location-group diagram, not a relationship or lineage graph.
  // All membership and counts come from the saved mapping; no directory I/O.
  function mapGroups() {
    if (!state.mapping) return [];
    const items = state.mapping.items;
    return state.mapping.groups.map((group) => {
      const members = items.filter((item) => item.group_id === group.id);
      const kind = members.length && members.every((item) => item.kind === "model") ? "model" : "dataset";
      return { ...group, kind, members,
        records: members.length, unique_paths: new Set(members.map((item) => item.current_path)).size };
    });
  }

  function previewMapGroup(id) {
    const detail = $("resource-map-detail");
    if (!detail) return;
    state.mapPreview = id || "";
    const group = mapGroups().find((entry) => entry.id === id);
    document.querySelectorAll("[data-map-group]").forEach((node) => node.classList.toggle("is-preview", node.dataset.mapGroup === id));
    if (!group) {
      detail.innerHTML = '<strong class="map-detail-title">从分组进入资料</strong><p class="map-detail-meta">悬停或聚焦节点查看记录数与位置数；点击或按 Enter 进入该组。连线只表示逻辑公共库下的资料分组。</p>';
      return;
    }
    const readable = group.members.filter((item) => item.checks?.readable === true).length;
    detail.innerHTML = `<strong class="map-detail-title">${escape(group.label)}</strong><p class="map-detail-meta">${number(group.records)} 条登记记录 · ${number(group.unique_paths)} 个不同位置 · rmp 入口可读 ${number(readable)} 条</p><p class="map-detail-meta">${escape(group.description || "位置与名称导航分组，不表示逻辑资源合并。")}</p><button type="button" class="map-detail-action text-link" data-map-select="${escape(group.id)}">浏览这组资料 ${icon("arrow")}</button>`;
  }

  function updateMapSelection() {
    document.querySelectorAll("[data-map-group]").forEach((node) => {
      const active = node.dataset.mapGroup === state.resourceGroup;
      node.classList.toggle("is-active", active);
      node.setAttribute("aria-pressed", String(active));
    });
  }

  function selectMapGroup(id) {
    if (!state.mapping?.groups.some((group) => group.id === id)) return;
    clearTimeout(state.resourceSearchTimer);
    // Keep the user's text/view filters; changing location should not silently reset them.
    state.resourceQuery = $("resource-search").value.trim();
    state.resourceGroup = id;
    state.resourcePage = 1;
    renderResources();
    previewMapGroup(id);
    focusResourceResults();
  }

  function renderResourceMap() {
    const container = $("resource-map");
    const panel = $("resource-map-panel");
    const summary = $("resource-map-summary");
    if (!container || !panel) return;
    const groups = mapGroups();
    if (summary) summary.textContent = state.mapping ? `${number(groups.length)} 个资料组 · ${number(state.mapping.items.length)} 条登记记录 · 按存放位置导航` : "资料分布随目录说明一起载入";
    if (panel.hidden) return;
    if (!state.mapping) {
      container.innerHTML = '<p class="mapping-loading">资料分布尚未载入。完成访问授权后，使用已保存的目录快照绘制。</p>';
      return;
    }
    if (state.mapRenderedFor === state.mapping) { updateMapSelection(); return; }
    state.mapRenderedFor = state.mapping;
    const columns = 7, cellWidth = 126, rowHeight = 110, firstX = 225;
    const maximum = Math.max(1, ...groups.map((group) => group.records));
    let top = 30;
    const sections = [], links = [], nodes = [];
    for (const kind of ["dataset", "model"]) {
      const members = groups.filter((group) => group.kind === kind);
      if (!members.length) continue;
      const rows = Math.ceil(members.length / columns);
      const rootY = top + (rows - 1) * rowHeight / 2 + 38;
      const total = members.reduce((sum, group) => sum + group.records, 0);
      const root = kind === "model" ? "模型公共库" : "数据公共库";
      sections.push(`<g class="map-root" data-map-kind="${kind}" aria-label="${root}，${number(total)} 条登记记录"><circle cx="73" cy="${rootY}" r="33"/><text class="map-root-count" x="73" y="${rootY + 6}" text-anchor="middle">${number(total)}</text><text class="map-root-label" x="73" y="${rootY + 58}" text-anchor="middle">${root}</text></g>`);
      members.forEach((group, index) => {
        const x = firstX + (index % columns) * cellWidth;
        const y = top + Math.floor(index / columns) * rowHeight + 38;
        const radius = Math.sqrt(100 + 576 * group.records / maximum);
        const rawLabel = String(group.label);
        const separator = rawLabel.includes(" · ") ? " · " : " / ";
        const pieces = rawLabel.split(separator);
        const labels = pieces.length > 1 ? [pieces.shift(), pieces.join(separator)] : [rawLabel];
        const short = (text) => Array.from(text).length > 18 ? Array.from(text).slice(0, 17).join("") + "…" : text;
        links.push(`<path class="map-link" data-map-kind="${kind}" d="M 106 ${rootY} C 142 ${rootY}, ${x - 55} ${y}, ${x - radius} ${y}"/>`);
        nodes.push(`<g class="map-node" data-map-group="${escape(group.id)}" data-map-kind="${kind}" role="button" tabindex="0" aria-pressed="${state.resourceGroup === group.id}" aria-label="${escape(group.label)}，${number(group.records)} 条登记记录，${number(group.unique_paths)} 个不同位置。按 Enter 筛选资料。"><title>${escape(group.label)} · ${number(group.records)} 条记录 · ${number(group.unique_paths)} 个位置</title><rect class="map-node-hit" x="${x - 58}" y="${y - 31}" width="116" height="99" rx="12" fill="transparent"/><circle class="map-node-circle" cx="${x}" cy="${y}" r="${radius.toFixed(2)}"/><text class="map-node-count" x="${x}" y="${y + 4}" text-anchor="middle">${number(group.records)}</text>${labels.map((label, line) => `<text class="map-node-label" x="${x}" y="${y + 43 + line * 15}" text-anchor="middle">${escape(short(label))}</text>`).join("")}</g>`);
      });
      top += rows * rowHeight + 35;
    }
    if (!groups.length) {
      container.innerHTML = '<p class="mapping-loading">当前目录没有可展示的资料分组。</p>';
    } else {
      container.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="resource-map-svg" viewBox="0 0 1080 ${top}" role="group" aria-labelledby="map-svg-title map-svg-description"><title id="map-svg-title">公共区资料分组分布</title><desc id="map-svg-description">两个逻辑公共库及其资料组。圆面积随登记记录数增加，并设最小可读大小；数字为精确记录数，不代表容量。连线只表示存放分组，不表示数据派生血缘。Tab 选择节点，方向键移动，Enter 或空格筛选。</desc><g aria-hidden="true">${links.join("")}</g>${sections.join("")}${nodes.join("")}</svg>`;
    }
    const legend = $("resource-map-legend");
    if (legend) legend.textContent = "数字 = 登记记录数 · 圆面积随记录数增加（含可读下限） · 连线 = 存放分组，不表示派生血缘或容量。Tab / 方向键选择，Enter 进入。";
    previewMapGroup(state.resourceGroup);
    updateMapSelection();
    reveal(container.querySelectorAll("svg"));
  }

  async function api(path, options = {}) {
    const response = await fetch(path, { credentials: "same-origin", ...options, headers: { Accept: "application/json", ...(options.headers || {}) } });
    let data;
    try { data = await response.json(); } catch { data = null; }
    if (response.status === 401) {
      if (path !== "/api/session") showAuth();
      const error = new Error(data?.error?.message || "访问会话已过期，请重新输入访问令牌。");
      error.code = "unauthenticated";
      throw error;
    }
    if (!response.ok) {
      const error = new Error(data?.error?.message || `接口请求失败（${response.status}）`);
      error.code = data?.error?.code;
      throw error;
    }
    if (data === null) throw new Error("接口未返回有效的 JSON 数据。");
    return data;
  }

  function showAuth() {
    state.platformReady = false;
    clearTimeout(state.serversPollTimer);
    state.serversPollTimer = null;
    state.ingestionController?.abort();
    state.serversController?.abort();
    state.literatureController?.abort();
    state.authEnabled = true;
    state.authenticated = false;
    state.assetController?.abort();
    state.mappingController?.abort();
    state.refreshController?.abort();
    $("refresh").classList.remove("is-refreshing");
    $("refresh").disabled = false;
    $("logout").hidden = true;
    if ($("asset-dialog").open) $("asset-dialog").close();
    clearCatalog();
    if (!$("auth-dialog").open) {
      $("auth-error").hidden = true;
      $("auth-dialog").showModal();
      $("auth-token").focus();
    }
    updateAgentCode();
  }

  function clearCatalog() {
    stopAnimations();
    state.servers = null;
    state.literature = null;
    $("servers-grid").replaceChildren();
    $("servers-observed").textContent = "登录后查看服务器观察。";
    $("compute-launcher-status").textContent = "等待访问授权";
    $("literature-results").replaceChildren();
    $("literature-summary").textContent = "登录后查看文献与来源索引。";
    $("literature-page-summary").textContent = "—";
    $("literature-category").innerHTML = '<option value="">全部类别</option>';
    $("literature-domain").innerHTML = '<option value="">全部网站</option>';
    $("literature-prev").disabled = true;
    $("literature-next").disabled = true;
    state.summary = null;
    state.items = [];
    state.total = 0;
    state.mapping = null;
    state.guide = null;
    state.ingestion = null;
    $("ingestion-mode").dataset.mode = "not-configured";
    $("ingestion-mode").textContent = "等待访问授权";
    $("ingestion-state-description").textContent = "登录后查看增补任务与规则 worker 状态。";
    $("ingestion-observed").textContent = "";
    $("ingestion-counts").replaceChildren();
    $("ingestion-jobs").replaceChildren();
    $("ingestion-published").replaceChildren();
    $("ingestion-queue-limit").textContent = "只读状态";
    $("storage-summary").textContent = "登录后查看存储清单与迁移核验。";
    $("storage-content").replaceChildren();
    $("physical-summary").replaceChildren();
    $("physical-summary").hidden = true;
    $("storage-details").open = false;
    $("domain-datasets-path").textContent = "/data/datasets";
    $("domain-models-path").textContent = "/data/models";
    $("research-guide-categories").replaceChildren();
    $("research-guide-steps").replaceChildren();
    $("research-guide-terms").replaceChildren();
    $("research-guide-tips").replaceChildren();
    $("research-guide-start").hidden = true;
    $("research-guide-status").hidden = false;
    $("research-guide-status").textContent = "登录后查看研究资源导览。";
    $("clear-resource-topic").hidden = true;
    state.mappingIndex.clear();
    state.mapRenderedFor = null;
    state.mapPreview = "";
    $("resource-map")?.replaceChildren();
    $("resource-map-detail")?.replaceChildren();
    if ($("resource-map-panel")) $("resource-map-panel").hidden = true;
    if ($("toggle-resource-map")) {
      $("toggle-resource-map").setAttribute("aria-expanded", "false");
      $("toggle-resource-map").innerHTML = `${icon("grid")}查看资源分布${icon("arrow")}`;
    }
    if ($("resource-map-summary")) $("resource-map-summary").textContent = "登录后查看资料分布";
    if ($("resource-map-legend")) $("resource-map-legend").textContent = "";
    if ($("stat-groups")) $("stat-groups").textContent = "—";
    for (const id of ["stat-total", "stat-paths", "stat-weights", "stat-readable", "nav-count", "catalog-total", "gap-count"]) $(id).textContent = "—";
    $("resource-content").replaceChildren();
    $("resource-groups").textContent = "登录后查看资料分组";
    $("resource-results-label").textContent = "登录后查看资料说明";
    $("resource-page-summary").textContent = "—";
    $("resource-prev").disabled = true;
    $("resource-next").disabled = true;
    $("mapping-error").hidden = true;
    $("verification-line").textContent = "核验依据为已保存的观察快照，不是实时服务器状态。";
    $("stat-access-note").textContent = "入口可读不代表全部文件可读";
    $("stat-model-note").textContent = "模型集合另列；未验证可运行性";
    $("asset-rows").replaceChildren();
    $("drawer-content").replaceChildren();
    $("scope-content").textContent = "登录后查看收录范围与来源。";
    $("scope-summary").textContent = "";
    $("scope-summary").hidden = true;
    $("category-options").replaceChildren();
    $("filter-server").innerHTML = '<option value="">全部服务器</option>';
    $("catalog-state").hidden = true;
    $("summary-error").hidden = true;
    for (const id of ["kind-chart", "server-chart", "status-chart"]) $(id).innerHTML = '<div class="chart-loading">登录后查看统计</div>';
    $("results-label").textContent = "请先登录资源目录";
    $("page-summary").textContent = "—";
    $("updated-label").textContent = "等待访问授权";
    $("previous-page").disabled = true;
    $("next-page").disabled = true;
  }

  function updateAgentCode() {
    const ingestionHeader = state.authEnabled ? ' -H "Authorization: Bearer $DATA_CENTER_TOKEN"' : "";
    $("ingestion-agent-code").textContent = [
      state.authEnabled ? "# 先设置管理员提供的 DATA_CENTER_TOKEN；只读调用" : "# 开发模式未启用访问令牌；只读调用",
      `curl -sS${ingestionHeader} "${window.location.origin}/api/ingestion/manifest"`,
      `curl -sS${ingestionHeader} "${window.location.origin}/api/ingestion/status"`,
    ].join("\n");
    const authHeader = state.authEnabled ? ' -H "Authorization: Bearer $DATA_CENTER_TOKEN"' : "";
    const comments = state.authEnabled ? "# 由管理员提供令牌，先设置 DATA_CENTER_TOKEN\n# 读取接口清单与资源约束\n" : "# 读取接口清单与资源约束\n";
    $("agent-code").textContent = `${comments}curl -sS${authHeader} \\\n  "${location.origin}/api/agent/manifest"`;
  }

  async function copyText(value, button) {
    if (!known(value)) { toast("此字段尚未记录"); return; }
    try {
      if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(String(value));
      else {
        const textarea = document.createElement("textarea");
        textarea.className = "clipboard-fallback";
        textarea.value = String(value);
        const host = $("asset-dialog").open ? $("asset-dialog") : document.body;
        host.append(textarea);
        textarea.focus();
        textarea.select();
        const copied = document.execCommand("copy");
        textarea.remove();
        if (!copied) throw new Error("copy failed");
      }
      toast("已复制到剪贴板");
      if (button) {
        const previousLabel = button.getAttribute("aria-label");
        button.setAttribute("aria-label", "已复制");
        button.classList.add("copied");
        window.setTimeout(() => { button.classList.remove("copied"); if (previousLabel) button.setAttribute("aria-label", previousLabel); }, 1800);
        button.focus({ preventScroll: true });
      }
    } catch { toast("自动复制不可用，请选中文本后复制。"); }
  }

  function toast(message) {
    clearTimeout(state.toastTimer);
    $("toast").textContent = message;
    $("toast").hidden = false;
    state.toastTimer = setTimeout(() => { $("toast").hidden = true; }, 3500);
  }

  function renderScope(summary) {
    let scopeHTML = "";
    const scope = summary.scope;
    const scopeHighlights = scope && typeof scope === "object" && !Array.isArray(scope) ? [scope["说明"]].filter(Boolean) : [];
    $("scope-summary").textContent = scopeHighlights.join(" ");
    $("scope-summary").hidden = !scopeHighlights.length;
    if (scope && typeof scope === "object" && !Array.isArray(scope)) {
      scopeHTML = Object.entries(scope).map(([key, value]) => `<p><strong>${escape(key)}</strong> ${escape(stringValue(value))}</p>`).join("");
    } else if (Array.isArray(scope)) scopeHTML = `<ul>${scope.map((value) => `<li>${escape(stringValue(value))}</li>`).join("")}</ul>`;
    else scopeHTML = `<p>${escape(scope || "来源文档中已登记的公共数据集与模型；完整性与核验范围以各资源记录为准。")}</p>`;
    const sources = Array.isArray(summary.sources) ? summary.sources : summary.sources && typeof summary.sources === "object" ? Object.entries(summary.sources).map(([name, source]) => typeof source === "object" ? { name, ...source } : { name, ref: source }) : [];
    if (sources.length) {
      scopeHTML += `<h3>来源与证据 · ${number(sources.length)} 项</h3><div class="source-list">${sources.map((source, index) => {
        if (typeof source === "string") return `<span>${escape(source)}</span>`;
        const url = source.url || source.source_url;
        const safe = url ? safeURL(url) : null;
        const label = source.name || source.title || source.ref || `来源 ${index + 1}`;
        return safe ? `<a href="${escape(safe)}" target="_blank" rel="noopener noreferrer">${escape(label)} ${icon("external")}</a>` : `<span>${escape(label)}</span>`;
      }).join("")}</div>`;
    }
    $("scope-content").innerHTML = scopeHTML;
  }

  function renderChart(target, values, filter) {
    const entries = Object.entries(values || {}).sort((a, b) => Number(b[1]) - Number(a[1]));
    if (!entries.length) { target.innerHTML = '<div class="chart-loading">尚无已登记数据</div>'; return; }
    const max = Math.max(...entries.map(([, value]) => Number(value) || 0), 1);
    target.innerHTML = entries.map(([key, value]) => {
      const label = filter === "kind" ? kindInfo(key).label : filter === "status" ? statuses[key] || key : key || "未记录";
      if (filter === "status") return `<button type="button" class="chart-button status-chart-row" data-filter="${filter}" data-value="${escape(key)}" aria-label="筛选${escape(label)}，${number(value)} 条"><span class="chart-name">${statusBadge(key)}</span><span class="chart-value">${number(value)}</span></button>`;
      return `<button type="button" class="chart-button" data-filter="${filter}" data-value="${escape(key)}" aria-label="筛选${escape(label)}，${number(value)} 条"><span class="chart-labels"><span class="chart-name">${filter === "server" ? icon("server") : ""}${escape(label)}</span><span class="chart-value">${number(value)}</span></span><progress class="chart-progress" max="${max}" value="${Number(value) || 0}" aria-hidden="true"></progress></button>`;
    }).join("");
  }

  function renderSummary(summary) {
    state.summary = summary;
    $("stats-grid").setAttribute("aria-busy", "false");
    renderOverviewCounts();
    $("nav-count").textContent = number(summary.total);
    $("catalog-total").textContent = number(summary.total);
    updateObservationLabel();
    renderStorageStatus();
    renderScope(summary);
    renderChart($("kind-chart"), summary.by_kind, "kind");
    renderChart($("server-chart"), summary.by_server, "server");
    renderChart($("status-chart"), summary.by_status, "status");
    const servers = Object.keys(summary.by_server || {}).filter(Boolean);
    if (state.query.server && !servers.includes(state.query.server)) servers.push(state.query.server);
    $("filter-server").innerHTML = `<option value="">全部服务器</option>${servers.map((server) => `<option value="${escape(server)}">${escape(server)}</option>`).join("")}`;
    $("filter-server").value = state.query.server;
    const categories = summary.categories || Object.keys(summary.by_category || {});
    $("category-options").innerHTML = categories.filter(Boolean).map((category) => `<option value="${escape(category)}"></option>`).join("");
    $("summary-error").hidden = true;
  }

  function renderOverviewCounts() {
    const summary = state.mapping?.summary;
    const total = summary?.records ?? state.summary?.total;
    const readable = summary?.readable ?? state.summary?.by_status?.verified;
    const restricted = summary?.restricted ?? state.summary?.by_status?.restricted;
    $("stat-total").textContent = number(total);
    $("stat-paths").textContent = number(summary?.unique_paths);
    $("stat-weights").textContent = number(summary?.known_weights);
    if ($("stat-groups")) $("stat-groups").textContent = number(state.mapping?.groups.length);
    $("stat-readable").innerHTML = `${number(readable)}<span class="stat-denominator">/ ${number(total)}</span>`;
    $("stat-access-note").textContent = known(restricted) ? `另有 ${number(restricted)} 条入口访问受限` : "入口可读不代表全部文件可读";
    if (state.mapping) {
      const collections = state.mapping.items.filter((item) => item.kind === "model" && item.subtype === "directory_collection").length;
      $("stat-model-note").textContent = `另有 ${number(collections)} 个模型目录集合 · 未验证可运行性`;
      $("verification-line").textContent = `观察时路径存在 ${number(summary?.exists)} 条，存在性未知 ${number(summary?.existence_unknown)} 条。访问可读性按 rmp 账号记录；以上为保存的观察快照，不是实时状态。`;
    }
  }

  function mappingLink(url, label, className = "text-link") {
    const safe = url ? safeURL(url) : null;
    return safe ? `<a href="${escape(safe)}" class="${escape(className)}" target="_blank" rel="noopener noreferrer">${escape(label)}${icon("external")}</a>` : "";
  }

  function mappingQuantity(item) {
    const quantity = item.documentation?.quantity || {};
    if (known(quantity.primary_value) && quantity.unit) return `${quantity.primary_value} ${quantity.unit}`;
    if (known(quantity.file_count)) return `${number(quantity.file_count)} 个文件（非样本数）`;
    return "数量或计数单位待补充";
  }

  function researchSourceList(sources, className = "research-source-list") {
    if (!Array.isArray(sources)) return "";
    const entries = sources.filter((entry) => entry && typeof entry === "object");
    return entries.length ? `<ul class="${className}">${entries.map((entry) => `<li>${mappingLink(entry.url, entry.label || "参考资料") || `<strong>${escape(entry.label || "参考资料")}</strong>`}${entry.scope ? `<span>${escape(entry.scope)}</span>` : ""}</li>`).join("")}</ul>` : "";
  }

  function researchList(values, ordered = false) {
    const items = textList(values);
    const tag = ordered ? "ol" : "ul";
    return items.length ? `<${tag} class="research-list${ordered ? " research-ordered" : ""}">${items.map((text) => `<li>${escape(text)}</li>`).join("")}</${tag}>` : "";
  }

  function renderResearchGuide() {
    const guide = state.guide;
    if (!guide) return;
    $("research-guide-title").textContent = guide.title || "研究资源导览";
    $("research-guide-intro").textContent = guide.introduction || "从研究问题出发，了解现有资料与可复用的工具。";
    $("research-guide-status").hidden = !!guide.categories.length;
    $("research-guide-status").textContent = guide.categories.length ? "" : "研究类别说明尚待补充，资料目录仍可直接浏览。";
    $("research-guide-categories").innerHTML = guide.categories.map((category, index) => `<article class="guide-category${state.resourceTopic === category.id ? " active" : ""}" data-guide-category="${escape(category.id)}"><div class="guide-category-top"><span>${String(index + 1).padStart(2, "0")} / RESEARCH</span><span>${number(category.counts?.records)} 条目录记录</span></div><h3><button type="button" data-topic="${escape(category.id)}" aria-pressed="${state.resourceTopic === category.id}">${escape(category.label)}</button></h3><p>${escape(category.intro || "")}</p><details><summary>用途与第一步 <span aria-hidden="true">＋</span></summary><div class="guide-category-detail">${textList(category.use_cases).length ? `<h4>可以研究什么</h4>${researchList(category.use_cases)}` : ""}${textList(category.first_steps).length ? `<h4>先从这里开始</h4>${researchList(category.first_steps, true)}` : ""}${researchSourceList(category.sources)}<p class="guide-count-note">${number(category.counts?.unique_paths)} 个不同存储路径。分类用于发现资料，不等同独立数据集数。</p></div></details><button type="button" class="text-link guide-browse" data-topic="${escape(category.id)}" aria-pressed="${state.resourceTopic === category.id}">浏览相关资料${icon("arrow")}</button></article>`).join("");
    const steps = Array.isArray(guide.newcomer_steps) ? guide.newcomer_steps : [];
    $("research-guide-steps").innerHTML = steps.map((step) => `<li><strong>${escape(typeof step === "string" ? step : step.title || "")}</strong>${typeof step === "object" && step.description ? `<p>${escape(step.description)}</p>` : ""}</li>`).join("");
    const terms = Array.isArray(guide.terms) ? guide.terms : [];
    $("research-guide-terms").innerHTML = terms.length ? `<h3>几个常用词</h3><dl>${terms.map((entry) => `<div><dt>${escape(entry.term || "")}</dt><dd>${escape(entry.description || "")}</dd></div>`).join("")}</dl>` : "";
    $("research-guide-tips").innerHTML = textList(guide.tips).length ? `<h3>使用提示</h3>${researchList(guide.tips)}` : "";
    $("research-guide-start").hidden = !steps.length && !terms.length && !textList(guide.tips).length;
  }

  async function loadResearchGuide(signal) {
    try {
      const guide = await api("/api/research-guide", { signal });
      if (signal?.aborted) return;
      if (!Array.isArray(guide.categories)) throw new Error("研究导览格式不完整");
      state.guide = guide;
      if (state.resourceTopic && !topicFor(state.resourceTopic)) state.resourceTopic = "";
      renderResearchGuide();
      renderResources();
    } catch (error) {
      if (error.name === "AbortError" || error.code === "unauthenticated") return;
      $("research-guide-status").hidden = false;
      $("research-guide-status").textContent = state.guide ? "导览更新暂未完成，保留上次说明。" : "研究导览暂不可用，下方资料搜索仍可使用。";
    }
  }

  function renderMappingGroups() {
    const groups = state.mapping?.groups || [];
    $("resource-groups").innerHTML = `<button type="button" class="resource-group${!state.resourceGroup ? " active" : ""}" data-group="" aria-pressed="${!state.resourceGroup}"><span>全部资料</span><b>${number(state.mapping?.items.length)}</b></button>${groups.map((group) => `<button type="button" class="resource-group${state.resourceGroup === group.id ? " active" : ""}" data-group="${escape(group.id)}" aria-pressed="${state.resourceGroup === group.id}" title="${escape(group.description || group.basis || "")}"><span>${escape(group.label)}</span><b>${number(group.records)}</b></button>`).join("")}`;
    const gapFields = new Map();
    for (const item of state.mapping?.items || []) for (const gap of item.gaps || []) {
      const field = gap.field || gap.label;
      const current = gapFields.get(field) || { label: gap.label, count: 0 };
      current.count += 1;
      gapFields.set(field, current);
    }
    $("gap-filter").innerHTML = '<option value="">全部待补事项</option>' + Array.from(gapFields).map(([field, gap]) => `<option value="${escape(field)}">${escape(gap.label)} · ${number(gap.count)}</option>`).join("");
    if (!gapFields.has(state.resourceGap)) state.resourceGap = "";
    $("gap-filter").value = state.resourceGap;
    $("gap-count").textContent = number(state.mapping?.summary?.records_with_gaps ?? state.mapping?.items.filter((item) => item.gaps?.length).length);
  }

  function resourceCard(item) {
    const doc = { ...(item.documentation || {}) };
    const research = researchFor(item);
    const topicLabels = (state.guide?.categories || []).filter((category) => (category.asset_ids || []).includes(item.asset_id)).map((category) => category.label);
    const researchUses = textList(research.research_uses).slice(0, 2);
    const taskLabels = [...new Set([...topicLabels, ...textList(research.modalities), ...textList(research.languages)])].slice(0, 3);
    doc.record_role = [doc.category, doc.record_role].filter(Boolean).join(" · ");
    const gaps = item.gaps || [];
    const relationships = item.relationships || [];
    const source = (item.evidence || []).map((evidence) => evidence.label).filter(Boolean)[0] || "来源证据待补充";
    const location = storageInfo(item);
    return `<article class="resource-card"><div class="resource-card-top"><span class="record-subtype ${kindClass(item.kind)}">${escape(subtypeText(item.subtype))}</span><span class="resource-version">${escape(versionText(item))}</span></div><h3><button type="button" data-asset="${escape(item.asset_id)}">${escape(item.display_name || "未命名资料")}</button></h3><p class="resource-purpose">${escape(researchSummary(item))}</p>${researchUses.length ? `<div class="resource-use-cases"><span>适合研究</span><ul>${researchUses.map((use) => `<li>${escape(use)}</li>`).join("")}</ul></div>` : ""}${taskLabels.length ? `<div class="resource-task-labels">${taskLabels.map((label) => `<span>${escape(label)}</span>`).join("")}</div>` : ""}<dl class="resource-facts"><div><dt>内容</dt><dd>${escape(doc.record_role || subtypeText(item.subtype))}</dd></div><div><dt>台账</dt><dd>${escape(mappingQuantity(item))}</dd></div><div><dt>证据</dt><dd title="${escape(source)}">${escape(source)}</dd></div></dl>${physicalCompact(item)}<div class="resource-path" title="${escape(location.current)}">${icon("server")}<code>${escape(location.current || "位置待补充")}</code></div>${location.storage ? `<div class="resource-storage-line">${migrationBadge(location)}${location.aliases.length ? `<span>${number(location.aliases.length)} 个兼容路径核验</span>` : ""}</div>` : ""}<div class="resource-card-meta"><span class="status-badge ${item.checks?.access === "readable" ? "verified" : item.checks?.access === "restricted" ? "restricted" : "documented"}">${escape(mappingAccessText(item))}</span><button type="button" class="gap-link" data-asset="${escape(item.asset_id)}" data-detail-section="detail-gaps">${gaps.length ? `${number(gaps.length)} 项待补说明` : "查看说明完整性"}</button></div>${relationships.length ? `<p class="relationship-count">${number(relationships.length)} 项映射关系候选 · 尚未确认合并或血缘</p>` : ""}<div class="resource-card-actions"><button type="button" class="text-link" data-asset="${escape(item.asset_id)}">查看资料说明${icon("arrow")}</button>${mappingLink(item.card_url, "独立资料卡")}</div></article>`;
  }

  function renderResourceCards(items) {
    return `<div class="resource-card-grid">${items.map(resourceCard).join("")}</div>`;
  }

  function renderResourceMapping(items) {
    return `<div class="mapping-table-scroll"><table class="mapping-table"><caption class="sr-only">资料登记身份、当前存储位置和兼容路径映射</caption><thead><tr><th scope="col">资料 / 登记身份</th><th scope="col">当前存储位置</th><th scope="col">兼容路径 / 计划目标</th><th scope="col">版本与映射关系</th></tr></thead><tbody>${items.map((item) => {
      const location = storageInfo(item);
      return `<tr><td><button type="button" class="mapping-name" data-asset="${escape(item.asset_id)}">${escape(item.display_name)}</button><span class="mapping-subtype">${escape(subtypeText(item.subtype))}</span><code class="registry-id" title="${escape(item.registry_id)}">${escape(item.registry_id)}</code></td><td class="mapping-storage-cell"><code class="mapping-current-path">${escape(location.current)}</code>${migrationBadge(location)}<small>位置观察：${escape(dateText(item.checks?.observed_at, true))}</small></td><td class="mapping-storage-cell">${location.aliases.length ? location.aliases.map((alias) => `<small>兼容路径 · ${escape(alias.host || "主机未记录")}</small><code class="mapping-current-path">${escape(alias.path)}</code><small>${escape(alias.state === "verified" ? "已核验" : alias.state || "状态未记录")} · ${escape(dateText(alias.verified_at, true))}</small>`).join("") : '<span class="mapping-muted">暂无兼容路径核验</span>'}${location.planned ? `<small>计划目标 · 尚未切换</small><code class="proposed-path">${escape(location.planned)}</code>` : ""}<button type="button" class="text-link" data-asset="${escape(item.asset_id)}" data-detail-section="detail-path">位置与核验详情${icon("arrow")}</button></td><td><span>${escape(versionText(item))}</span>${item.relationships?.length ? `<button type="button" class="text-link" data-asset="${escape(item.asset_id)}" data-detail-section="detail-relationships">${number(item.relationships.length)} 项候选关系${icon("arrow")}</button>` : '<small class="mapping-muted">暂无已登记关系</small>'}${mappingLink(item.card_url, "完整资料卡")}</td></tr>`;
    }).join("")}</tbody></table></div>`;
  }

  function renderResourceGaps(items) {
    return `<div class="gap-list">${items.map((item) => {
      const gaps = (item.gaps || []).filter((gap) => !state.resourceGap || (gap.field || gap.label) === state.resourceGap);
      return `<article class="gap-record"><div class="gap-record-heading"><div><span class="record-subtype">${escape(subtypeText(item.subtype))}</span><h3><button type="button" class="mapping-name" data-asset="${escape(item.asset_id)}">${escape(item.display_name)}</button></h3></div><button type="button" class="text-link" data-asset="${escape(item.asset_id)}" data-detail-section="detail-gaps">查看说明${icon("arrow")}</button></div><ul>${gaps.map((gap) => `<li><strong>${escape(gap.label || gap.field)}</strong><span>${escape(gap.reason || "需要补充说明与证据")}</span></li>`).join("")}</ul><div class="gap-record-bottom"><span>补充依据后再确认；当前仅列说明待办</span>${mappingLink(item.kind === "model" ? "/docs/templates/model-README.md" : "/docs/templates/dataset-README.md", "参考说明模板")}</div></article>`;
    }).join("")}</div>`;
  }

  function updateResourceURL() {
    const url = new URL(location.href);
    const values = { view: state.resourceView === "cards" ? "" : state.resourceView, group: state.resourceGroup, topic: state.resourceTopic, rq: state.resourceQuery, gap: state.resourceView === "gaps" ? state.resourceGap : "", rp: state.resourcePage > 1 ? String(state.resourcePage) : "" };
    for (const [key, value] of Object.entries(values)) { if (value) url.searchParams.set(key, value); else url.searchParams.delete(key); }
    history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
  }

  function renderResources() {
    if (!state.mapping) return;
    state.resourcePageSize = state.resourceView === "gaps" ? 6 : 12;
    const query = state.resourceQuery.toLocaleLowerCase();
    let items = state.mapping.items.filter((item) => !state.resourceGroup || item.group_id === state.resourceGroup);
    const topic = topicFor(state.resourceTopic);
    if (topic) {
      const ids = new Set(Array.isArray(topic.asset_ids) ? topic.asset_ids : []);
      items = items.filter((item) => Array.isArray(topic.asset_ids) ? ids.has(item.asset_id) : (topic.group_ids || []).includes(item.group_id));
    }
    if (query) items = items.filter((item) => {
      const research = researchFor(item);
      return [item.display_name, item.registry_id, ...locationSearchTerms(item), item.description, item.documentation?.summary, item.documentation?.category, item.documentation?.record_role, subtypeText(item.subtype), research.background, research.summary, ...textList(research.research_uses), ...textList(research.contents), ...textList(research.getting_started), ...textList(research.starter_notes), ...textList(research.languages), ...textList(research.modalities), ...textList(research.topics), ...(item.gaps || []).flatMap((gap) => [gap.label, gap.reason])].filter(Boolean).join(" ").toLocaleLowerCase().includes(query);
    });
    if (state.resourceView === "gaps") items = items.filter((item) => item.gaps?.length && (!state.resourceGap || item.gaps.some((gap) => (gap.field || gap.label) === state.resourceGap)));
    state.resourceFiltered = items;
    const totalPages = Math.max(1, Math.ceil(items.length / state.resourcePageSize));
    state.resourcePage = Math.min(Math.max(1, state.resourcePage), totalPages);
    const start = (state.resourcePage - 1) * state.resourcePageSize;
    const visible = items.slice(start, start + state.resourcePageSize);
    const group = state.mapping.groups.find((entry) => entry.id === state.resourceGroup);
    $("resource-results-label").textContent = `${topic ? `${topic.label} · ` : ""}${group?.label || "全部分组"} · ${number(items.length)} 条${state.resourceView === "gaps" ? "含待补说明的记录" : "目录登记记录"}`;
    $("resource-view-note").textContent = state.resourceView === "mapping" ? "登记 ID 关联当前位置与兼容路径。计划目标仅在明确核验切换后生效；相同路径、父子目录或版本关系仍是候选。" : state.resourceView === "gaps" ? "逐条列出用途、版本、维护人、来源等说明缺项。这里展示待办，没有启动整理任务或自动修改资料。" : group?.description || "资源卡保留目录记录的身份；集合、衍生资料与权重入口分别标识。分组仅用于导航，不表示已合并为同一资源。";
    $("resource-content").setAttribute("aria-busy", "false");
    $("resource-content").innerHTML = !items.length ? `<div class="catalog-state">${icon("search")}<h3>没有匹配的资料${state.resourceView === "gaps" ? "待办" : ""}</h3><p>调整资料分组、关键词或待补事项筛选后重试。</p><button type="button" class="button button-secondary" data-resource-reset>清除筛选</button></div>` : state.resourceView === "mapping" ? renderResourceMapping(visible) : state.resourceView === "gaps" ? renderResourceGaps(visible) : renderResourceCards(visible);
    $("resource-page-summary").textContent = items.length ? `显示 ${start + 1}–${Math.min(start + state.resourcePageSize, items.length)} 条，共 ${number(items.length)} 条` : "暂无可显示记录";
    $("resource-page-label").textContent = `${state.resourcePage} / ${totalPages}`;
    $("resource-prev").disabled = state.resourcePage <= 1;
    $("resource-next").disabled = state.resourcePage >= totalPages;
    $("gap-filter-wrap").hidden = state.resourceView !== "gaps";
    $("reset-resource-filters").hidden = !state.resourceGroup && !state.resourceQuery && !state.resourceGap && !state.resourceTopic;
    $("clear-resource-topic").hidden = !state.resourceTopic;
    document.querySelectorAll("[data-topic]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.topic === state.resourceTopic)));
    document.querySelectorAll("[data-guide-category]").forEach((card) => card.classList.toggle("active", card.dataset.guideCategory === state.resourceTopic));
    document.querySelectorAll("[data-resource-view]").forEach((button) => { const active = button.dataset.resourceView === state.resourceView; button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active)); });
    document.querySelectorAll("[data-group]").forEach((button) => { const active = button.dataset.group === state.resourceGroup; button.classList.toggle("active", active); button.setAttribute("aria-pressed", String(active)); });
    updateMapSelection();
    reveal($("resource-content").querySelectorAll(".resource-card, .gap-record"));
    updateResourceURL();
  }

  async function loadMapping() {
    state.mappingController?.abort();
    const controller = new AbortController();
    state.mappingController = controller;
    $("resource-content").setAttribute("aria-busy", "true");
    $("mapping-error").hidden = true;
    if (!state.mapping) $("resource-content").innerHTML = '<div class="catalog-state"><h3>正在读取资料说明…</h3><p>正在建立登记记录、存储位置与说明之间的映射。</p></div>';
    try {
      const data = await api("/api/resource-mapping", { signal: controller.signal });
      if (controller.signal.aborted) return;
      if (!Array.isArray(data.items) || !Array.isArray(data.groups)) throw new Error("资料映射格式不完整");
      state.mapping = data;
      state.mappingIndex = new Map(data.items.map((item) => [item.asset_id, item]));
      if (state.resourceGroup && !data.groups.some((group) => group.id === state.resourceGroup)) state.resourceGroup = "";
      renderMappingGroups();
      renderResources();
      renderOverviewCounts();
      updateObservationLabel();
      renderStorageStatus();
      renderResourceMap();
    } catch (error) {
      if (error.name === "AbortError" || error.code === "unauthenticated") return;
      $("resource-content").setAttribute("aria-busy", "false");
      $("mapping-error").innerHTML = `资料说明暂时无法读取：${escape(error.message)}。下方原始台账仍可独立使用。<button type="button" data-action="retry-mapping">重试</button>`;
      $("mapping-error").hidden = false;
      $("resource-results-label").textContent = state.mapping ? "更新失败 · 显示上次读取的说明" : "资料说明读取失败";
      if (!state.mapping) { $("resource-content").replaceChildren(); $("resource-groups").textContent = "资料分组暂不可用"; }
    }
  }

  function resetResourceFilters() {
    clearTimeout(state.resourceSearchTimer);
    state.resourceQuery = "";
    state.resourceGroup = "";
    state.resourceTopic = "";
    state.resourceGap = "";
    state.resourcePage = 1;
    $("resource-search").value = "";
    $("gap-filter").value = "";
    renderResources();
  }

  function renderSkeleton() {
    $("table-container").hidden = false;
    $("catalog-state").hidden = true;
    $("asset-rows").innerHTML = Array.from({ length: 6 }, () => `<tr aria-hidden="true">${Array.from({ length: 6 }, () => '<td><div class="skeleton"></div><div class="skeleton short"></div></td>').join("")}</tr>`).join("");
    $("table-container").setAttribute("aria-busy", "true");
    $("results-label").textContent = "正在载入资源…";
    $("previous-page").disabled = true;
    $("next-page").disabled = true;
  }

  function renderAssets(data) {
    state.items = Array.isArray(data.items) ? data.items : [];
    state.total = Number(data.total) || 0;
    state.page = Number(data.page) || state.page;
    const totalPages = Math.max(1, Math.ceil(state.total / state.pageSize));
    const hasFilters = Object.values(state.query).some(Boolean);
    $("reset-filters").hidden = !hasFilters;
    $("results-label").textContent = `${hasFilters ? "筛选结果" : "全部资源"} · ${number(state.total)} 条${hasFilters && state.summary ? ` / 共 ${number(state.summary.total)} 条登记` : ""}`;
    $("table-container").setAttribute("aria-busy", "false");
    $("page-label").textContent = `${state.page} / ${totalPages}`;
    $("page-summary").textContent = state.total ? `显示 ${(state.page - 1) * state.pageSize + 1}–${Math.min(state.page * state.pageSize, state.total)} 条，共 ${number(state.total)} 条` : "暂无可显示的资源";
    $("previous-page").disabled = state.page <= 1;
    $("next-page").disabled = state.page >= totalPages;
    if (!state.items.length) {
      $("table-container").hidden = true;
      $("catalog-state").hidden = false;
      $("catalog-state").innerHTML = `${icon("search")}<h3>${hasFilters ? "没有找到匹配的资源" : "资源目录暂时为空"}</h3><p>${hasFilters ? "试试更短的关键词，或调整类型、服务器与状态筛选。" : "导入真实资产台账后，资源将在这里显示。"}</p>${hasFilters ? '<button type="button" class="button button-secondary" data-action="reset">清除全部筛选</button>' : '<button type="button" class="button button-secondary" data-action="retry">重新加载</button>'}`;
      $("asset-rows").replaceChildren();
      return;
    }
    $("catalog-state").hidden = true;
    $("table-container").hidden = false;
    $("asset-rows").innerHTML = state.items.map((asset) => {
      const id = escape(asset.id);
      const kind = kindInfo(asset.kind);
      const location = storageInfo(mappingFor(asset.id), asset);
      const count = known(asset.file_count) ? `${number(asset.file_count)} 个文件` : known(asset.record_count) ? `${number(asset.record_count)} 条记录` : "计数未记录";
      return `<tr><td><div class="asset-name-wrap"><span class="asset-icon ${kindClass(asset.kind)}">${icon(kind.icon)}</span><div class="asset-name-content"><button type="button" class="asset-title" data-asset="${id}" title="${escape(asset.name)}">${escape(asset.name || "未命名资源")}</button><p class="asset-description" title="${escape(mappingFor(asset.id) ? researchSummary(mappingFor(asset.id)) : asset.description || asset.category || "")}">${escape(mappingFor(asset.id) ? researchSummary(mappingFor(asset.id)) : asset.description || asset.category || "用途尚未记录")}</p></div></div></td><td>${kindBadge(asset.kind)}</td><td><div class="server-name" title="${escape(asset.server)}">${icon("server")}${escape(asset.server || "服务器未记录")}</div><div class="path-preview" title="${escape(location.current)}" dir="ltr">${escape(location.current || "路径未记录")}</div></td><td><div class="size-value">${sizeText(asset.size_bytes)}</div><div class="size-detail">${count}</div></td><td>${statusBadge(asset.status)}</td><td><button type="button" class="row-arrow" data-asset="${id}" aria-label="查看 ${escape(asset.name || "资源")} 的详情">${icon("arrow")}</button></td></tr>`;
    }).join("");
  }

  function showCatalogError(error) {
    if (error.name === "AbortError" || error.code === "unauthenticated") return;
    $("table-container").hidden = true;
    $("table-container").setAttribute("aria-busy", "false");
    $("catalog-state").hidden = false;
    $("catalog-state").innerHTML = `${icon("info")}<h3>暂时无法读取资源目录</h3><p>${escape(error.message)}。请检查本地服务与连接后重试。</p><button type="button" class="button button-secondary" data-action="retry">重新加载</button>`;
    $("results-label").textContent = "读取失败";
    $("page-summary").textContent = "—";
    $("previous-page").disabled = true;
    $("next-page").disabled = true;
  }

  function updateURL() {
    const url = new URL(location.href);
    for (const [key, value] of Object.entries(state.query)) { if (value) url.searchParams.set(key, value); else url.searchParams.delete(key); }
    if (state.page > 1) url.searchParams.set("page", String(state.page)); else url.searchParams.delete("page");
    history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
  }

  async function loadAssets() {
    state.assetController?.abort();
    const controller = new AbortController();
    state.assetController = controller;
    const params = new URLSearchParams({ page: String(state.page), page_size: String(state.pageSize) });
    for (const [key, value] of Object.entries(state.query)) if (value) params.set(key, value);
    updateURL();
    renderSkeleton();
    try {
      const data = await api(`/api/assets?${params.toString()}`, { signal: controller.signal });
      if (controller.signal.aborted) return;
      if (!data.items?.length && data.total > 0 && state.page > Math.ceil(data.total / state.pageSize)) {
        state.page = Math.max(1, Math.ceil(data.total / state.pageSize));
        return loadAssets();
      }
      renderAssets(data);
    } catch (error) { showCatalogError(error); }
  }

  async function refresh() {
    state.refreshController?.abort();
    const controller = new AbortController();
    state.refreshController = controller;
    $("refresh").classList.add("is-refreshing");
    $("refresh").disabled = true;
    $("stats-grid").setAttribute("aria-busy", "true");
    await Promise.allSettled([
      api("/api/summary", { signal: controller.signal }).then((data) => { if (!controller.signal.aborted) renderSummary(data); }).catch((error) => {
        if (error.name === "AbortError" || error.code === "unauthenticated") return;
        $("summary-error").innerHTML = `概览读取失败：${escape(error.message)} <button type="button" data-action="retry-all">重新加载</button>`;
        $("summary-error").hidden = false;
        $("stats-grid").setAttribute("aria-busy", "false");
        $("updated-label").textContent = state.summary ? "更新失败 · 显示上次读取结果" : "暂时无法连接目录";
      }),
      loadAssets(),
      loadMapping(),
      loadResearchGuide(controller.signal),
      loadIngestion(controller.signal),
      loadServers(controller.signal),
      loadLiterature(controller.signal),
    ]);
    if (!controller.signal.aborted) {
      $("refresh").classList.remove("is-refreshing");
      $("refresh").disabled = false;
    }
  }

  function syncFiltersFromInputs() {
    state.query = { q: $("search").value.trim(), kind: $("filter-kind").value, server: $("filter-server").value, status: $("filter-status").value, category: $("filter-category").value.trim() };
    state.page = 1;
    $("reset-filters").hidden = !Object.values(state.query).some(Boolean);
    return loadAssets();
  }

  function resetFilters() {
    clearTimeout(state.searchTimer);
    $("filters").reset();
    state.query = { q: "", kind: "", server: "", status: "", category: "" };
    state.page = 1;
    $("reset-filters").hidden = true;
    loadAssets();
  }

  function researchDetailSections(item) {
    const research = researchFor(item);
    if (!Object.keys(research).length) return "";
    const uses = textList(research.research_uses);
    const contents = textList(research.contents);
    const steps = textList(research.getting_started).length ? research.getting_started : research.starter_notes;
    const io = research.inference_io || {};
    const languages = textList(research.languages);
    const modalities = textList(research.modalities);
    const evidence = research.provenance_note || research.evidence_basis;
    return `<section class="drawer-section research-reading" id="detail-research"><h3>${icon("book")}研究背景与上手路径</h3>${research.background ? `<p class="research-background">${escape(research.background)}</p>` : ""}${uses.length ? `<div class="research-subsection"><h4>可以用来研究什么</h4>${researchList(uses)}</div>` : ""}${contents.length ? `<div class="research-subsection"><h4>资料里有什么</h4>${researchList(contents)}</div>` : ""}${known(io.input) || known(io.output) || languages.length || modalities.length ? `<dl class="detail-grid">${known(io.input) ? `<div><dt>输入</dt><dd>${escape(stringValue(io.input))}</dd></div>` : ""}${known(io.output) ? `<div><dt>输出</dt><dd>${escape(stringValue(io.output))}</dd></div>` : ""}${languages.length ? `<div><dt>语言</dt><dd>${escape(languages.join("、"))}</dd></div>` : ""}${modalities.length ? `<div><dt>资料模态</dt><dd>${escape(modalities.join("、"))}</dd></div>` : ""}</dl>` : ""}${textList(steps).length ? `<div class="research-subsection" id="detail-getting-started"><h4>如何开始使用</h4>${researchList(steps, true)}</div>` : ""}${textList(research.caveats).length ? `<details class="detail-disclosure research-caveats"><summary>适用范围与研究提醒</summary>${researchList(research.caveats)}</details>` : ""}${Array.isArray(research.sources) && research.sources.length || evidence ? `<details class="detail-disclosure"><summary>这段说明的参考依据</summary>${researchSourceList(research.sources)}${evidence ? `<p class="research-evidence-note">${escape(stringValue(evidence))}</p>` : ""}</details>` : ""}</section>`;
  }

  function mappingDetailSections(item) {
    if (!item) return '<div class="detail-mapping-notice">此条资料说明尚未读取，以下保留原始台账。可在资料导航中重试加载完整说明。</div>';
    const doc = item.documentation || {};
    const quantity = doc.quantity || {};
    const version = item.version || {};
    const checks = item.checks || {};
    const field = (label, value) => `<div><dt>${escape(label)}</dt><dd>${escape(stringValue(value))}</dd></div>`;
    const sourceFields = doc.source_fields || {};
    const content = [doc.record_role, sourceFields["数据类型"], sourceFields["标注说明"]].filter(Boolean);
    const group = state.mapping?.groups.find((entry) => entry.id === item.group_id);
    const evidence = item.evidence || [];
    const gaps = item.gaps || [];
    const relationships = item.relationships || [];
    const relationLabels = { same_path: "同一存储位置", same_location: "共用存储位置（非同一资源）", same_path_candidate: "同一存储位置", parent_path: "父目录关系", parent_location: "父目录位置", parent_directory: "父目录关系", child_path: "子目录关系", child_location: "子目录位置", nested_path: "目录包含关系", path_ancestor: "目录包含关系", path_descendant: "目录包含关系", derived_from: "衍生来源候选", version_candidate: "版本关系候选", shared_location: "共享存储位置" };
    return `<nav class="drawer-quicknav" aria-label="资料说明快捷定位">${Object.keys(researchFor(item)).length ? `<button type="button" data-detail-jump="detail-research">研究与上手</button>` : ""}<button type="button" data-detail-jump="detail-purpose">用途与内容</button><button type="button" data-detail-jump="detail-path">存储与兼容路径</button>${physicalFor(item) ? `<button type="button" data-detail-jump="detail-physical">物理清点</button>` : ""}<button type="button" data-detail-jump="detail-relationships">映射关系</button><button type="button" data-detail-jump="detail-gaps">待补说明</button></nav><div class="registry-summary"><span>持久登记 ID</span><code>${escape(item.registry_id)}</code><p>登记身份用于关联说明与存储位置，不代表资料已冻结为发布版本。</p>${item.registration ? `<p class="registration-time">首次登记：${escape(dateText(item.registration.first_registered_at, true))} · 最近说明登记：${escape(dateText(item.registration.last_registered_at, true))}<br>登记时间不代表重新观察文件系统；位置核验时间见存储详情。</p>` : ""}<div>${mappingLink(item.card_url, "独立完整资料卡")}${mappingLink(item.card_markdown_url, "Markdown 说明")}</div></div>
      ${researchDetailSections(item)}
      <section class="drawer-section detail-readable" id="detail-purpose"><h3>${icon("book")}用途与内容说明</h3><p>${escape(doc.summary || item.description || "用途待补充")}</p>${content.length ? `<div class="content-description">${Array.from(new Set(content)).map((value) => `<p>${escape(value)}</p>`).join("")}</div>` : ""}<dl class="detail-grid">${field("研究方向 / 分类", doc.category)}${field("资料角色", subtypeText(item.subtype))}${field("导航分组", group?.label)}${field("维护人", doc.maintainer?.name || "尚未确认")}</dl><p class="drawer-note">${escape(doc.maintainer?.note || "文件系统所有者不自动视为资料维护人。")}</p>${Array.isArray(doc.notes) && doc.notes.length ? `<details class="detail-disclosure"><summary>补充说明与复用提示 · ${number(doc.notes.length)} 项</summary>${doc.notes.map((note) => `<p>${escape(stringValue(note))}</p>`).join("")}</details>` : ""}</section>
      <section class="drawer-section"><h3>${icon("feature")}历史台账数量与口径</h3><dl class="detail-grid">${field("来源记录的主要数量", quantity.primary_value)}${field("计数单位", quantity.unit)}${field("计数对应时间", dateText(quantity.as_of, true))}${field("已记录容量", sizeText(quantity.size_bytes))}</dl><p class="status-explanation">${escape(quantity.scope || "计数范围尚待说明。文件数不能直接解释为样本数、录音数或参与者人数。")}</p><p class="drawer-note">未知值不按零计算；不同范围的容量、父子目录与共享对象库不可直接求和。</p></section>
      <section class="drawer-section"><h3>${icon("layers")}版本与复用边界</h3><dl class="detail-grid">${field("发布版本", version.release_id || "尚未固定")}${field("上游 revision", version.upstream_revision)}</dl><p class="drawer-note">${escape(version.note || "目录日期、文件修改时间和观察时间不能代替发布版本。")}</p>${version.naming_hints?.length ? `<p class="drawer-note">目录命名线索（非确认版本）：${escape(version.naming_hints.join("、"))}</p>` : ""}<p class="drawer-note">使用许可：${escape(doc.license?.detail || "尚未核实；收录目录不代表获得使用或分发授权。")}</p></section>
      <section class="drawer-section"><h3>${icon("book")}说明证据与来源</h3><p class="drawer-note">整理台账是当前说明的证据，不自动等同上游来源、许可证或内容质量证明。</p>${evidence.length ? `<ul class="evidence-list">${evidence.map((entry) => `<li><strong>${escape(entry.label || entry.type || "说明证据")}</strong>${entry.url ? mappingLink(entry.url, "查看证据") : ""}${entry.ref ? `<code>${escape(entry.ref)}</code>` : ""}<span>证据时间：${escape(dateText(entry.observed_at, true))}</span></li>`).join("")}</ul>` : '<p class="drawer-note">尚无独立来源证据。</p>'}</section>
      <section class="drawer-section" id="detail-relationships"><h3>${icon("layers")}位置映射与关系候选</h3><p class="drawer-note">存储迁移状态见“存储与兼容路径”。本节的逻辑整理建议和关系候选不构成迁移回执。</p>${item.proposed_path?.path ? `<div class="proposed-location"><strong>逻辑整理建议 · 未执行</strong><code>${escape(item.proposed_path.path)}</code></div>` : ""}${relationships.length ? `<ul class="relationship-list">${relationships.map((relation) => { const target = mappingFor(relation.target_asset_id); return `<li><span class="candidate-label">候选关系 · 待确认</span><strong>${escape(relationLabels[relation.type] || relation.type)}</strong><button type="button" class="text-link" data-related-asset="${escape(relation.target_asset_id)}">${escape(target?.display_name || relation.target_registry_id || relation.target_asset_id)}${icon("arrow")}</button><p>${escape(relation.basis || "依据现有目录结构产生的候选关系，尚未确认资源合并或衍生血缘。")}</p></li>`; }).join("")}</ul>` : '<p class="drawer-note">尚无已登记的关系候选。</p>'}</section>
      <section class="drawer-section" id="detail-gaps"><h3>${icon("file")}待补说明 <span class="count-pill">${number(gaps.length)}</span></h3>${gaps.length ? `<ul class="detail-gap-list">${gaps.map((gap) => `<li><strong>${escape(gap.label || gap.field)}</strong><p>${escape(gap.reason || "需补充依据后确认。")}</p></li>`).join("")}</ul>` : '<p class="drawer-note">当前未列出说明缺项，不代表内容质量已经验证。</p>'}<div class="drawer-actions">${mappingLink(item.kind === "model" ? "/docs/templates/model-README.md" : "/docs/templates/dataset-README.md", "参考说明模板")}${mappingLink("/docs/standards.html", "查看整理规范")}</div><p class="drawer-note">增补流程已制定，接收尚未启用；这里仅展示说明和待办。</p></section>`;
  }

  function renderDetails(asset) {
    const mapping = mappingFor(asset.id);
    const location = storageInfo(mapping, asset);
    const kind = kindInfo(asset.kind);
    const sourceURL = asset.source_url ? safeURL(asset.source_url) : null;
    const formats = Array.isArray(asset.formats) ? asset.formats.join("、") : stringValue(asset.formats);
    const metadata = asset.metadata && typeof asset.metadata === "object" ? asset.metadata : {};
    const subtype = metadata.subtype ?? metadata["资源子类型"] ?? metadata["数据类型"] ?? metadata["原始数据类型"];
    const detailURL = `${window.location.origin}/api/assets/${encodeURIComponent(asset.id)}`;
    const authHeader = state.authEnabled ? ' -H "Authorization: Bearer $DATA_CENTER_TOKEN"' : "";
    const curl = `curl -sS${authHeader} \\\n  "${detailURL}"`;
    const detail = (label, value, mono = false) => `<div><dt>${escape(label)}</dt><dd${mono ? ' class="mono"' : ""}>${escape(stringValue(value))}</dd></div>`;
    $("drawer-content").innerHTML = `
      <div class="drawer-heading"><span class="asset-icon ${kindClass(asset.kind)}">${icon(kind.icon)}</span><div><h2 id="drawer-title">${escape(asset.name || "未命名资源")}</h2><p class="drawer-id">${escape(asset.id)}</p></div></div>
      <div class="drawer-badges">${kindBadge(asset.kind)}${statusBadge(asset.status)}${asset.category ? `<span class="tag">${escape(asset.category)}</span>` : ""}</div>
      <p class="drawer-description">${escape(mapping?.documentation?.summary || researchFor(mapping).summary || asset.description || "此资源的用途与描述尚未记录。")}</p>
      ${known(subtype) ? `<dl class="detail-grid">${detail("资源子类型", subtypeText(subtype))}</dl>` : ""}
      ${mappingDetailSections(mapping)}
      ${physicalDetail(mapping, asset)}
      <section class="drawer-section"><h3>${icon("server")}存储位置与兼容路径</h3>${storageDetail(mapping, asset)}<dl class="detail-grid">${detail("服务器", asset.server)}${detail("文件系统所有者（非维护人）", asset.owner)}${detail("原登记容量", sizeText(asset.size_bytes))}${detail("原登记文件数", known(asset.file_count) ? number(asset.file_count) : null)}${detail("原登记记录数", known(asset.record_count) ? number(asset.record_count) : null)}${detail("文件格式", formats || null)}</dl><p class="drawer-note">容量与计数按来源口径展示，可能包含父子目录或同源版本重叠，不宜直接跨条目求和；文件数不等于研究样本数。</p>${Array.isArray(asset.tags) && asset.tags.length ? `<div class="drawer-tags">${asset.tags.map((tag) => `<span class="tag">${escape(tag)}</span>`).join("")}</div>` : ""}</section>
      <section class="drawer-section"><h3>${icon("shield")}观察状态与访问边界</h3><div class="status-explanation">${escape(statusExplanations[asset.status] || "该资源的核验边界以来源记录为准。")}</div><dl class="detail-grid">${detail("路径存在性", mapping?.checks?.exists === true ? "观察时存在" : mapping?.checks?.exists === false ? "观察时未找到" : "待核实")}${detail("rmp 入口访问", mapping ? mappingAccessText(mapping) : statuses[asset.status])}${detail("观察时间（非实时）", dateText(mapping?.checks?.observed_at || asset.verified_at, true))}${detail("访问说明", asset.access)}</dl>${asset.notes ? `<p class="drawer-note">${escape(asset.notes)}</p>` : ""}</section>
      <section class="drawer-section"><h3>${icon("book")}原始台账引用</h3><div class="source-box">${sourceURL ? `<a href="${escape(sourceURL)}" class="text-link" target="_blank" rel="noopener noreferrer">打开登记证据文档 ${icon("external")}</a>` : "未记录外部台账链接"}${asset.source_ref ? `<div class="source-ref">${escape(asset.source_ref)}</div>` : ""}</div><p class="drawer-note">此处引用不自动构成上游来源或授权证明。</p></section>
      <section class="drawer-section"><h3>${icon("file")}完整元数据 <span class="count-pill">${number(Object.keys(metadata).length)}</span></h3>${Object.keys(metadata).length ? '<dl class="metadata-list" id="asset-metadata"></dl>' : '<p class="drawer-note">尚无额外元数据。</p>'}</section>
      <section class="drawer-section"><h3>${icon("code")}Agent 调用</h3><pre class="drawer-code" id="asset-curl">${escape(curl)}</pre><div class="drawer-actions"><button type="button" id="copy-asset-curl" class="button button-secondary">${icon("copy")}复制调用示例</button><a href="/api/assets/${encodeURIComponent(asset.id)}" target="_blank" rel="noopener" class="text-link">查看 JSON ${icon("external")}</a></div><p class="drawer-note">接口返回资源元数据。${state.authEnabled ? "调用前请将管理员提供的访问令牌设置为 DATA_CENTER_TOKEN 环境变量。" : ""}</p></section>`;
    if ($("asset-metadata")) {
      for (const [key, value] of Object.entries(metadata)) {
        const row = document.createElement("div");
        row.className = "metadata-row";
        const label = document.createElement("dt");
        label.textContent = key;
        const content = document.createElement("dd");
        if (value !== null && typeof value === "object") {
          const pre = document.createElement("pre");
          pre.textContent = JSON.stringify(value, null, 2);
          content.append(pre);
        } else content.textContent = stringValue(value);
        row.append(label, content);
        $("asset-metadata").append(row);
      }
    }
    $("copy-path").addEventListener("click", (event) => copyText(location.current, event.currentTarget));
    $("copy-asset-curl").addEventListener("click", (event) => copyText(curl, event.currentTarget));
    $("asset-path").closest(".drawer-section").id = "detail-path";
    $("drawer-content").scrollTop = 0;
  }

  async function openAsset(id, trigger, sectionId) {
    state.detailController?.abort();
    const controller = new AbortController();
    state.detailController = controller;
    if (trigger && !$("asset-dialog").contains(trigger)) state.drawerTrigger = trigger;
    $("drawer-content").innerHTML = '<h2 id="drawer-title">正在读取资源…</h2><div class="drawer-loading" aria-busy="true"><div class="skeleton"></div><div class="skeleton short"></div></div>';
    if (!$("asset-dialog").open) $("asset-dialog").showModal();
    document.body.classList.add("drawer-open");
    $("close-drawer").focus();
    try {
      const asset = await api(`/api/assets/${encodeURIComponent(id)}`, { signal: controller.signal });
      if (!controller.signal.aborted) {
        renderDetails(asset);
        if (sectionId && $(sectionId)) $(sectionId).scrollIntoView({ block: "start" });
      }
    } catch (error) {
      if (error.name === "AbortError" || error.code === "unauthenticated") return;
      $("drawer-content").innerHTML = `<div class="catalog-state"><h2 id="drawer-title">无法读取资源详情</h2><p>${escape(error.message)}</p><button type="button" class="button button-secondary" id="retry-detail">重试</button></div>`;
      $("retry-detail").addEventListener("click", () => openAsset(id, trigger, sectionId));
    }
  }

  function bindEvents() {
    document.querySelectorAll("[data-platform-link]").forEach((link) => link.addEventListener("click", () => selectPlatform(link.dataset.platformLink)));
    document.querySelectorAll('a[href="#overview"]').forEach((link) => link.addEventListener("click", () => selectPlatform("home")));
    const syncPlatform = () => selectPlatform(location.hash.slice(1));
    window.addEventListener("hashchange", syncPlatform);
    document.addEventListener("visibilitychange", () => scheduleServerRefresh(true));
    syncPlatform();
    $("servers-refresh").addEventListener("click", () => loadServers());
    const searchLiterature = () => {
      state.literatureQuery = { q: $("literature-search").value.trim(), category: $("literature-category").value, domain: $("literature-domain").value };
      state.literaturePage = 1;
      loadLiterature();
    };
    $("literature-filters").addEventListener("submit", (event) => { event.preventDefault(); searchLiterature(); });
    for (const id of ["literature-category", "literature-domain"]) $(id).addEventListener("change", searchLiterature);
    $("literature-reset").addEventListener("click", () => { $("literature-filters").reset(); searchLiterature(); });
    $("literature-prev").addEventListener("click", () => { if (state.literaturePage > 1) { state.literaturePage -= 1; loadLiterature(); $("literature").scrollIntoView({ block: "start" }); } });
    $("literature-next").addEventListener("click", () => { state.literaturePage += 1; loadLiterature(); $("literature").scrollIntoView({ block: "start" }); });
    $("literature-results").addEventListener("click", (event) => { const button = event.target.closest("[data-literature-asset]"); if (button) openAsset(button.dataset.literatureAsset, button); });
    $("ingestion-refresh").addEventListener("click", () => loadIngestion());
    $("ingestion-copy-cli").addEventListener("click", (event) => copyText($("ingestion-cli-code").textContent, event.currentTarget));
    $("ingestion-copy-agent").addEventListener("click", (event) => copyText($("ingestion-agent-code").textContent, event.currentTarget));
    $("research-guide-categories").addEventListener("click", (event) => {
      const button = event.target.closest("[data-topic]");
      if (!button || !topicFor(button.dataset.topic)) return;
      state.resourceTopic = state.resourceTopic === button.dataset.topic ? "" : button.dataset.topic;
      state.resourcePage = 1;
      renderResources();
      focusResourceResults();
    });
    $("clear-resource-topic").addEventListener("click", () => { state.resourceTopic = ""; state.resourcePage = 1; renderResources(); });
    $("refresh").addEventListener("click", refresh);
    $("toggle-resource-map")?.addEventListener("click", () => {
      const panel = $("resource-map-panel");
      if (!panel) return;
      panel.hidden = !panel.hidden;
      $("toggle-resource-map").setAttribute("aria-expanded", String(!panel.hidden));
      $("toggle-resource-map").innerHTML = `${icon("grid")}${panel.hidden ? "查看资源分布" : "收起资源分布"}${icon("arrow")}`;
      if (!panel.hidden) renderResourceMap();
    });
    $("resource-map")?.addEventListener("pointerover", (event) => {
      const node = event.target.closest("[data-map-group]");
      if (node && state.mapPreview !== node.dataset.mapGroup) previewMapGroup(node.dataset.mapGroup);
    });
    $("resource-map")?.addEventListener("focusin", (event) => {
      const node = event.target.closest("[data-map-group]");
      if (node) previewMapGroup(node.dataset.mapGroup);
    });
    $("resource-map")?.addEventListener("click", (event) => {
      const node = event.target.closest("[data-map-group]");
      if (node) selectMapGroup(node.dataset.mapGroup);
    });
    $("resource-map")?.addEventListener("keydown", (event) => {
      const node = event.target.closest("[data-map-group]");
      if (!node) return;
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectMapGroup(node.dataset.mapGroup);
      } else if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        const nodes = Array.from($("resource-map").querySelectorAll("[data-map-group]"));
        const index = nodes.indexOf(node);
        const offset = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[event.key] || 0;
        const next = event.key === "Home" ? 0 : event.key === "End" ? nodes.length - 1 : (index + offset + nodes.length) % nodes.length;
        nodes[next]?.focus({ preventScroll: true });
        nodes[next]?.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "instant" });
      }
    });
    $("resource-map-detail")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-map-select]");
      if (button) selectMapGroup(button.dataset.mapSelect);
    });
    document.addEventListener("visibilitychange", () => { if (document.hidden) stopAnimations(); });
    motionPreference.addEventListener("change", () => { if (motionPreference.matches) stopAnimations(); });
    document.querySelectorAll("[data-resource-view]").forEach((button) => button.addEventListener("click", () => {
      state.resourceView = button.dataset.resourceView;
      state.resourcePage = 1;
      renderResources();
    }));
    $("resource-groups").addEventListener("click", (event) => {
      const button = event.target.closest("[data-group]");
      if (!button) return;
      state.resourceGroup = button.dataset.group;
      state.resourcePage = 1;
      renderResources();
    });
    $("resource-search").addEventListener("input", () => {
      clearTimeout(state.resourceSearchTimer);
      state.resourceSearchTimer = setTimeout(() => { state.resourceQuery = $("resource-search").value.trim(); state.resourcePage = 1; renderResources(); }, 250);
    });
    $("gap-filter").addEventListener("change", () => { state.resourceGap = $("gap-filter").value; state.resourcePage = 1; renderResources(); });
    $("reset-resource-filters").addEventListener("click", resetResourceFilters);
    $("resource-content").addEventListener("click", (event) => {
      const button = event.target.closest("[data-asset]");
      if (button) openAsset(button.dataset.asset, button, button.dataset.detailSection);
      if (event.target.closest("[data-resource-reset]")) resetResourceFilters();
    });
    $("resource-prev").addEventListener("click", () => { if (state.resourcePage > 1) { state.resourcePage -= 1; renderResources(); $("resources").scrollIntoView({ block: "start" }); } });
    $("resource-next").addEventListener("click", () => { if (state.resourcePage < Math.ceil(state.resourceFiltered.length / state.resourcePageSize)) { state.resourcePage += 1; renderResources(); $("resources").scrollIntoView({ block: "start" }); } });
    $("mapping-error").addEventListener("click", (event) => { if (event.target.closest('[data-action="retry-mapping"]')) loadMapping(); });
    $("drawer-content").addEventListener("click", (event) => {
      const button = event.target.closest("[data-related-asset]");
      if (button) openAsset(button.dataset.relatedAsset, button);
      const copyLocation = event.target.closest("[data-copy-location]");
      if (copyLocation) copyText(copyLocation.dataset.copyLocation, copyLocation);
      const jump = event.target.closest("[data-detail-jump]");
      if (jump && $(jump.dataset.detailJump)) $(jump.dataset.detailJump).scrollIntoView({ block: "start" });
    });
    $("filters").addEventListener("submit", (event) => { event.preventDefault(); clearTimeout(state.searchTimer); syncFiltersFromInputs(); });
    $("search").addEventListener("input", () => { clearTimeout(state.searchTimer); state.searchTimer = setTimeout(syncFiltersFromInputs, 350); });
    for (const id of ["filter-kind", "filter-server", "filter-status", "filter-category"]) $(id).addEventListener("change", () => { clearTimeout(state.searchTimer); syncFiltersFromInputs(); });
    $("reset-filters").addEventListener("click", resetFilters);
    $("previous-page").addEventListener("click", () => { if (state.page > 1) { state.page -= 1; loadAssets(); $("catalog").scrollIntoView({ block: "start" }); } });
    $("next-page").addEventListener("click", () => { if (state.page < Math.ceil(state.total / state.pageSize)) { state.page += 1; loadAssets(); $("catalog").scrollIntoView({ block: "start" }); } });
    $("catalog-state").addEventListener("click", (event) => { const action = event.target.closest("[data-action]")?.dataset.action; if (action === "reset") resetFilters(); if (action === "retry") loadAssets(); });
    $("summary-error").addEventListener("click", (event) => { if (event.target.closest("[data-action]")) refresh(); });
    $("asset-rows").addEventListener("click", (event) => { const button = event.target.closest("[data-asset]"); if (button) openAsset(button.dataset.asset, button); });
    document.querySelector(".insights-grid").addEventListener("click", (event) => {
      const button = event.target.closest("[data-filter]");
      if (!button) return;
      $("filters").reset();
      $(button.dataset.filter === "kind" ? "filter-kind" : button.dataset.filter === "server" ? "filter-server" : "filter-status").value = button.dataset.value;
      clearTimeout(state.searchTimer);
      syncFiltersFromInputs();
      $("catalog").scrollIntoView({ block: "start" });
    });
    $("copy-agent").addEventListener("click", (event) => copyText($("agent-code").textContent, event.currentTarget));
    $("close-drawer").addEventListener("click", () => $("asset-dialog").close());
    $("asset-dialog").addEventListener("click", (event) => {
      if (event.target !== $("asset-dialog")) return;
      const rect = $("asset-dialog").getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) $("asset-dialog").close();
    });
    $("asset-dialog").addEventListener("close", () => { state.detailController?.abort(); document.body.classList.remove("drawer-open"); state.drawerTrigger?.focus({ preventScroll: true }); });
    document.addEventListener("keydown", (event) => {
      const inputActive = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName) || document.activeElement?.isContentEditable;
      if (event.key === "/" && !inputActive && !$("asset-dialog").open && !$("auth-dialog").open) { event.preventDefault(); selectPlatform("data-platform"); $("resource-search").focus(); $("resources").scrollIntoView({ block: "start" }); }
    });
    document.querySelectorAll("[data-nav]").forEach((link) => link.addEventListener("click", () => { document.querySelectorAll("[data-nav]").forEach((item) => item.classList.toggle("active", item === link)); }));
    if ("IntersectionObserver" in window) {
      const observer = new IntersectionObserver((entries) => {
        const entry = entries.filter((item) => item.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (entry) document.querySelectorAll("[data-nav]").forEach((link) => link.classList.toggle("active", link.dataset.nav === entry.target.id));
      }, { rootMargin: "-15% 0px -65% 0px", threshold: 0 });
      for (const id of ["research-guide", "resources", "catalog", "ingestion", "agent"]) observer.observe($(id));
    }
    $("auth-dialog").addEventListener("cancel", (event) => event.preventDefault());
    $("auth-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const token = $("auth-token").value;
      if (!token) return;
      $("auth-submit").disabled = true;
      $("auth-error").hidden = true;
      try {
        const result = await api("/api/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }) });
        $("auth-token").value = "";
        state.authEnabled = result.auth_enabled !== false;
        state.authenticated = true;
        state.platformReady = true;
        $("logout").hidden = !state.authEnabled;
        $("auth-dialog").close();
        updateAgentCode();
        await refresh();
        scheduleServerRefresh();
      } catch (error) {
        $("auth-error").textContent = error.code === "unauthenticated" ? "访问令牌无效，请核对后重试。" : `暂时无法登录：${error.message}`;
        $("auth-error").hidden = false;
        $("auth-token").value = "";
        $("auth-token").focus();
      } finally { $("auth-submit").disabled = false; }
    });
    $("logout").addEventListener("click", async () => {
      $("logout").disabled = true;
      try {
        await api("/api/session", { method: "DELETE" });
        state.assetController?.abort();
        state.mappingController?.abort();
        state.refreshController?.abort();
        state.detailController?.abort();
        state.ingestionController?.abort();
        $("refresh").classList.remove("is-refreshing");
        $("refresh").disabled = false;
        showAuth();
      } catch (error) { toast(`退出失败：${error.message}`); }
      finally { $("logout").disabled = false; }
    });
    window.addEventListener("popstate", () => { readURL(); loadAssets(); renderResources(); });
  }

  function readURL() {
    const params = new URLSearchParams(location.search);
    for (const key of Object.keys(state.query)) state.query[key] = (params.get(key) || "").trim();
    if (!["", "dataset", "model"].includes(state.query.kind)) state.query.kind = "";
    state.page = Math.max(1, parseInt(params.get("page"), 10) || 1);
    $("search").value = state.query.q;
    $("filter-kind").value = state.query.kind;
    $("filter-status").value = state.query.status;
    $("filter-category").value = state.query.category;
    if (state.query.server && !Array.from($("filter-server").options).some((option) => option.value === state.query.server)) {
      const option = new Option(state.query.server, state.query.server);
      $("filter-server").add(option);
    }
    $("filter-server").value = state.query.server;
    state.resourceView = ["cards", "mapping", "gaps"].includes(params.get("view")) ? params.get("view") : "cards";
    state.resourceQuery = (params.get("rq") || "").trim();
    state.resourceGroup = params.get("group") || "";
    state.resourceTopic = params.get("topic") || "";
    state.resourceGap = params.get("gap") || "";
    state.resourcePage = Math.max(1, parseInt(params.get("rp"), 10) || 1);
    $("resource-search").value = state.resourceQuery;
    $("gap-filter").value = state.resourceGap;
  }

  async function initialize() {
    readURL();
    bindEvents();
    updateAgentCode();
    try {
      const session = await api("/api/session");
      state.authEnabled = !!session.auth_enabled;
      state.authenticated = !!session.authenticated;
      $("logout").hidden = !state.authEnabled || !state.authenticated;
      updateAgentCode();
      if (state.authEnabled && !state.authenticated) { showAuth(); return; }
    } catch (error) {
      if (error.code === "unauthenticated") { showAuth(); return; }
      // Older development servers may not expose the session probe yet.
      // The resource endpoints remain the authority for access decisions.
    }
    state.platformReady = true;
    await refresh();
    scheduleServerRefresh();
  }

  initialize();
})();
