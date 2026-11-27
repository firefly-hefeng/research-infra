"use strict";

window.createResearchWorkspace = function ({ api, openAsset }) {
  const $ = (id) => document.getElementById(id);
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const normalize = (value) => String(value ?? "").normalize("NFKC").toLocaleLowerCase("zh-CN");
  const number = (value) => value.toLocaleString("zh-CN");
  const list = (value) => Array.isArray(value) ? value : [];
  const pageSize = 12;
  const tabLabels = { dataset: "全部数据资料", model: "全部模型", feishu: "全部台账记录" };
  const resourcePriority = new Map([
    ["数据资料", 0], ["语料入口", 0], ["派生录音", 0], ["模型权重", 0], ["派生特征", 1],
    ["特征表", 1], ["子库目录", 2], ["模型目录", 2], ["获取线索", 4],
  ]);
  const library = { data: null, request: null, tab: "dataset", theme: "", category: "", subcategory: "", page: 1, query: "" };
  const documents = { data: null, request: null, selected: "", focusHash: null, rendered: null };
  const home = { request: null, loaded: false, timer: null, signature: null };

  function linkURL(value) {
    if (typeof value !== "string" || !value.trim()) return null;
    try {
      const url = new URL(value, location.origin);
      return ["https:", "http:"].includes(url.protocol) ? url.href : null;
    } catch { return null; }
  }

  function formatDate(value, withTime = false) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.valueOf())) return "";
    return new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
      ...(withTime ? { hour: "2-digit", minute: "2-digit", hourCycle: "h23" } : {}),
    }).format(date);
  }

  function byTab(item, tab = library.tab) {
    return tab === "feishu" ? item.source === "feishu" : item.kind === tab;
  }

  function categoryOf(item) {
    return library.data.categories.find((category) => category.id === item.category_id);
  }

  function themeOf(item) {
    return list(library.data.themes).find((theme) => theme.id === item.theme_id);
  }

  function subcategoryOf(item) {
    return list(categoryOf(item)?.children).find((subcategory) => subcategory.id === item.subcategory_id);
  }

  function filterLibrary() {
    const words = normalize(library.query).trim().split(/\s+/).filter(Boolean);
    return library.data.items.filter((item) => {
      if (!byTab(item)) return false;
      if (!words.length) return true;
      const searchable = normalize([item.title, item.id, item.role, item.summary, item.status,
        ...list(item.aliases), ...list(item.use_cases), item.usage_note, themeOf(item)?.label, categoryOf(item)?.label, subcategoryOf(item)?.label,
        item.source === "feishu" ? "飞书 公司数据与申请台账" : "服务器目录"].join(" "));
      return words.every((word) => searchable.includes(word));
    });
  }

  function facetButton(attribute, value, label, count, current) {
    return `<button type="button" ${attribute}="${escape(value)}" aria-pressed="${current === value}"><span>${escape(label)}</span><small>${number(count)}</small></button>`;
  }

  function renderFacets(base) {
    const themes = list(library.data.themes);
    $("library-themes").innerHTML = [facetButton("data-library-theme", "", "全部标签", base.length, library.theme),
      ...themes.map((theme) => ({ ...theme, count: base.filter((item) => item.theme_id === theme.id).length }))
        .filter((theme) => theme.count || theme.id === library.theme)
        .map((theme) => facetButton("data-library-theme", theme.id, theme.label, theme.count, library.theme))].join("");
    const currentTheme = themes.find((theme) => theme.id === library.theme);
    if (currentTheme) base = base.filter((item) => item.theme_id === currentTheme.id);
    const categories = library.data.categories;
    const withCounts = categories.map((category) => ({ ...category, count: base.filter((item) => item.category_id === category.id).length }));
    const visible = withCounts.filter((category) => category.count || category.id === library.category);
    $("library-categories").hidden = themes.length > 0 && !currentTheme;
    $("library-categories").innerHTML = [facetButton("data-library-category", "", "全部大类", base.length, library.category),
      ...visible.map((category) => facetButton("data-library-category", category.id, category.label, category.count, library.category))].join("");
    const active = visible.find((category) => category.id === library.category);
    const children = list(active?.children).map((subcategory) => ({ ...subcategory, count: base.filter((item) => item.category_id === active.id && item.subcategory_id === subcategory.id).length }));
    const childButtons = children.filter((subcategory) => subcategory.count || subcategory.id === library.subcategory);
    $("library-selection").textContent = active?.label || currentTheme?.label || tabLabels[library.tab];
    $("library-subcategories").hidden = !childButtons.length;
    $("library-subcategories").innerHTML = childButtons.length ? [facetButton("data-library-subcategory", "", "全部细分类", active.count, library.subcategory),
      ...childButtons.map((subcategory) => facetButton("data-library-subcategory", subcategory.id, subcategory.label, subcategory.count, library.subcategory))].join("") : "";
  }

  function renderLedgerSource() {
    $("library-ledger-intro").hidden = library.tab !== "feishu";
    const source = list(library.data.sources).find((entry) => entry.id === "feishu");
    const url = linkURL(source?.url);
    if (url) $("library-ledger-link").href = url;
    const when = formatDate(source?.observed_at, true);
    const mode = { live: "最近同步", cached: "上次同步", snapshot: "台账快照", offline: "台账快照" }[source?.mode] || "来源记录";
    $("library-ledger-freshness").textContent = when ? `${mode} ${when}（北京时间）` : "飞书原表可查看最新变更。";
  }

  function libraryCard(item) {
    const category = categoryOf(item);
    const subcategory = subcategoryOf(item);
    const sourceLabel = item.source === "feishu" ? "飞书台账" : "服务器目录";
    const classification = [...new Set([themeOf(item)?.label, category?.label, subcategory?.label].filter(Boolean))].join(" / ");
    return `<article class="library-card">
      <div class="library-card-meta"><span>${escape(item.role || (item.kind === "model" ? "模型" : "数据资料"))}</span><small>${sourceLabel}</small></div>
      <h3><button type="button" data-library-item="${escape(item.id)}">${escape(item.title)}</button></h3>
      ${classification ? `<small class="library-card-path">${escape(classification)}</small>` : ""}
      <p>${escape(item.summary || "说明待补。")}</p>
      <div class="library-card-footer"><span>${escape(item.status || item.count_label || "")}</span><button type="button" class="workspace-link" data-library-item="${escape(item.id)}" aria-label="查看${escape(item.title)}的详细说明">查看资料 <span aria-hidden="true">↗</span></button></div>
    </article>`;
  }

  function ledgerTable(items) {
    const rows = items.map((item) => {
      const url = linkURL(item.source_url);
      return `<tr>
        <td>${escape(themeOf(item)?.label || "待核对")}</td>
        <td>${escape(categoryOf(item)?.label || "待归类")}</td>
        <td>${escape(subcategoryOf(item)?.label || "—")}</td>
        <th scope="row"><button type="button" class="workspace-link" data-library-item="${escape(item.id)}">${escape(item.title)}</button></th>
        <td>${escape(item.status || "—")}</td>
        <td>${url ? `<a href="${escape(url)}" target="_blank" rel="noopener noreferrer" class="workspace-link" aria-label="在飞书打开 ${escape(item.title)}">原记录 ↗</a>` : "—"}</td>
      </tr>`;
    }).join("");
    return `<div class="library-table-wrap" tabindex="0" role="region" aria-label="飞书台账数据表"><table class="library-table">
      <thead><tr><th scope="col">一级标签</th><th scope="col">研究大类</th><th scope="col">细分类</th><th scope="col">资料名称</th><th scope="col">台账状态</th><th scope="col">来源</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  }

  function renderLibrary() {
    if (!library.data) return;
    for (const tab of document.querySelectorAll("[data-library-tab]")) {
      const key = tab.dataset.libraryTab;
      tab.querySelector("[data-library-count]").textContent = number(library.data.items.filter((item) => byTab(item, key)).length);
    }
    const base = filterLibrary();
    renderFacets(base);
    renderLedgerSource();
    const items = base.filter((item) => (!library.theme || item.theme_id === library.theme)
      && (!library.category || item.category_id === library.category)
      && (!library.subcategory || item.subcategory_id === library.subcategory));
    if (library.tab !== "feishu") {
      items.sort((left, right) => (resourcePriority.get(left.role) ?? 3) - (resourcePriority.get(right.role) ?? 3));
    }
    const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
    library.page = Math.min(library.page, totalPages);
    const start = (library.page - 1) * pageSize;
    const shown = items.slice(start, start + pageSize);
    const quantityLabel = library.tab === "feishu" ? "条台账记录" : "条资料记录";
    const resultCount = items.length > pageSize
      ? `共 ${number(items.length)} ${quantityLabel}，当前显示 ${start + 1}–${start + shown.length}`
      : `共 ${number(items.length)} ${quantityLabel}`;
    const busy = Boolean(library.request);
    $("library-status").textContent = busy ? `正在刷新资料 · ${resultCount}` : resultCount;
    $("library-results").setAttribute("aria-busy", String(busy));
    $("library-results").innerHTML = !items.length
      ? '<p class="workspace-empty">当前筛选没有匹配的资料。</p>'
      : library.tab === "feishu" ? ledgerTable(shown) : `<div class="library-grid">${shown.map(libraryCard).join("")}</div>`;
    $("library-reset").hidden = !library.query && !library.theme && !library.category;
    $("library-pager").hidden = totalPages === 1;
    $("library-page").textContent = `第 ${library.page} / ${totalPages} 页`;
    $("library-prev").disabled = library.page <= 1;
    $("library-next").disabled = library.page >= totalPages;
  }

  async function loadLibrary(force) {
    if (library.data && !force) { renderLibrary(); return; }
    if (library.request) return;
    const request = new AbortController();
    library.request = request;
    $("library-retry").hidden = true;
    $("library-results").setAttribute("aria-busy", "true");
    $("library-status").textContent = "正在读取资料…";
    try {
      const data = await api("/api/platform/library", { signal: request.signal });
      if (request.signal.aborted) return;
      if (!Array.isArray(data.items) || !Array.isArray(data.categories)) throw new Error("Invalid resource catalog");
      library.data = data;
      library.request = null;
      renderLibrary();
    } catch (error) {
      if (request.signal.aborted || error.code === "unauthenticated") return;
      $("library-status").textContent = library.data ? "刷新失败，当前显示上次读取的资料。" : "";
      $("library-retry").hidden = false;
    } finally {
      if (library.request === request) {
        library.request = null;
        $("library-results").setAttribute("aria-busy", "false");
      }
    }
  }

  function showLibrary(hash, force) {
    const tab = hash === "library-models" ? "model" : hash === "feishu-ledger" ? "feishu" : "dataset";
    if (tab !== library.tab) Object.assign(library, { tab, theme: "", category: "", subcategory: "", page: 1 });
    for (const link of document.querySelectorAll("[data-library-tab]")) {
      if (link.dataset.libraryTab === tab) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
    $("library-selection").textContent = tabLabels[tab];
    $("library-ledger-intro").hidden = tab !== "feishu";
    return loadLibrary(force);
  }

  let activeDetailTrigger;
  function openLibraryItem(item, trigger) {
    const source = linkURL(item.source_url);
    const detail = linkURL(item.detail_url);
    const reference = linkURL(item.reference_url);
    const uses = list(item.use_cases).filter(Boolean);
    const category = categoryOf(item)?.label;
    const subcategory = subcategoryOf(item)?.label;
    const fromFeishu = item.source === "feishu";
    const assetId = item.asset_id || (item.id.startsWith("asset-") ? item.id : "");
    const external = source ? `<a class="button button-secondary" href="${escape(source)}" target="_blank" rel="noopener noreferrer">${fromFeishu ? "飞书原记录" : "资料来源"} ↗</a>` : "";
    const researchSource = reference && reference !== source ? `<a class="button button-secondary" href="${escape(reference)}" target="_blank" rel="noopener noreferrer">研究来源 ↗</a>` : "";
    const details = assetId ? `<button type="button" class="button button-secondary" data-library-asset="${escape(assetId)}">查看服务器目录记录</button>`
      : detail && detail !== source ? `<a class="button button-secondary" href="${escape(detail)}" target="_blank" rel="noopener noreferrer">资料详情 ↗</a>` : "";
    const facts = [
      ["来源", fromFeishu ? "公司数据与申请台账" : "服务器目录"],
      ["资料角色", item.role],
      ["来源状态", item.status],
      [fromFeishu ? "台账读取日期" : "目录核对日期", formatDate(item.observed_at)],
      ["已记录数量", item.count_label],
      ["数量来源日期", item.count_label && (formatDate(item.count_observed_at) || "未注明")],
      ["记录 ID", item.id],
    ];
    $("library-dialog-content").innerHTML = `<div class="document-kicker">${escape([...new Set([themeOf(item)?.label, category, subcategory].filter(Boolean))].join(" / "))}</div>
      <h2 id="library-dialog-title">${escape(item.title)}</h2>
      <p class="library-detail-summary">${escape(item.summary || "说明待补。")}</p>
      ${uses.length ? `<h3>研究用途</h3><ul>${uses.map((use) => `<li>${escape(use)}</li>`).join("")}</ul>` : ""}
      ${item.usage_note ? `<h3>使用条件</h3><p>${escape(item.usage_note)}</p>` : ""}
      <dl class="library-detail-meta">${facts.filter(([, value]) => value).map(([label, value]) => `<div><dt>${label}</dt><dd>${escape(value)}</dd></div>`).join("")}</dl>
      <div class="library-detail-links">${external}${researchSource}${details}</div>`;
    activeDetailTrigger = trigger;
    $("library-dialog").showModal();
    $("close-library-dialog").focus();
  }

  function focusDocumentHeading(heading) {
    if (!heading) return;
    heading.focus({ preventScroll: true });
    heading.scrollIntoView({ block: "start", behavior: "instant" });
  }

  function renderDocuments() {
    const items = documents.data;
    const selected = documents.selected === "" ? items[0] : items.find((item) => item.id === documents.selected);
    const groups = new Map();
    for (const item of items) {
      const name = item.category || "其他文档";
      if (!groups.has(name)) groups.set(name, []);
      groups.get(name).push(item);
    }
    const links = Array.from(groups, ([name, group]) => `<section><h3>${escape(name)}</h3>${group.map((item) =>
      `<a href="#documents/${encodeURIComponent(item.id)}" ${item.id === selected?.id ? 'aria-current="page"' : ""}>${escape(item.title)}</a>`).join("")}</section>`).join("");
    const options = Array.from(groups, ([name, group]) => `<optgroup label="${escape(name)}">${group.map((item) =>
      `<option value="${escape(item.id)}" ${item.id === selected?.id ? "selected" : ""}>${escape(item.title)}</option>`).join("")}</optgroup>`).join("");
    const index = links ? `<nav class="document-index" aria-label="原点文档目录"><h2>文档目录</h2>
      <div class="document-index-groups">${links}</div><select aria-label="选择原点文档" data-document-select>${selected ? "" : '<option value="">选择文档</option>'}${options}</select></nav>` : "";
    const workspace = $("workspace-documents");
    const shouldFocus = !$("documents").hidden && documents.focusHash === location.hash;
    const restoreFocus = selected && !$("documents").hidden
      && workspace.querySelector(".document-index [aria-current]")?.hash === `#documents/${encodeURIComponent(selected.id)}`
      && document.activeElement === workspace.querySelector(".document-reading h2");
    documents.focusHash = null;
    if (!selected) {
      documents.rendered = null;
      workspace.innerHTML = index;
      const message = documents.selected === "" ? "暂无已收录文档。" : "未找到这份文档。";
      $("documents-status").textContent = message + (links ? "可从目录选择已收录的文档。" : "");
      return;
    }
    const signature = JSON.stringify([selected.id, items]);
    if (signature === documents.rendered && workspace.querySelector(".document-reading")) {
      $("documents-status").textContent = "";
      if (shouldFocus) focusDocumentHeading(workspace.querySelector(".document-reading h2"));
      return;
    }
    documents.rendered = signature;
    const articleURL = linkURL(selected.url);
    const source = articleURL ? new URL(articleURL) : null;
    const liveWiki = selected.source_mode === "feishu_live" && source?.origin === "https://wcn5kauqqbj1.feishu.cn"
      && !source.username && !source.password && /^\/wiki\/[A-Za-z0-9]+$/.test(source.pathname) && !source.search && !source.hash;
    const localMarkdown = source?.origin === location.origin && source.pathname.startsWith("/docs/")
      && source.pathname.endsWith(".md") && !source.search && !source.hash;
    const segments = list(selected.sections);
    const content = segments.map((section) => {
      const paragraphs = list(section.paragraphs).map((paragraph) => `<p>${escape(paragraph)}</p>`).join("");
      const actions = list(section.links).map((link) => {
        const url = linkURL(link?.url);
        return url && link.label ? `<li><a class="workspace-link" href="${escape(url)}">${escape(link.label)}</a></li>` : "";
      }).join("");
      return `<section><h3>${escape(section.title)}</h3>${paragraphs}${actions ? `<ul class="document-links">${actions}</ul>` : ""}</section>`;
    }).join("");
    const readDate = selected.updated_at ? `导读更新 ${formatDate(selected.updated_at)}` : "";
    const reader = liveWiki ? `<div class="document-live">
      <p>正文、图表和附件由飞书按你的账户权限加载。若浏览器要求登录，请在新窗口打开原件。</p>
      <iframe title="${escape(selected.title)} · 飞书原件" src="${escape(articleURL)}" referrerpolicy="no-referrer"
        sandbox="allow-forms allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox allow-downloads" allowfullscreen></iframe>
      </div>` : localMarkdown ? `<details class="document-full-text"><summary>阅读平台原文</summary><pre aria-live="polite" data-document-markdown="${escape(source.pathname)}"></pre></details>` : "";
    $("documents-status").textContent = "";
    workspace.innerHTML = `${index}
      <article class="document-reading"><header>
      <div class="document-kicker">${escape([selected.category, liveWiki ? "飞书实时原件" : "", readDate].filter(Boolean).join(" · "))}</div>
      <h2 tabindex="-1">${escape(selected.title)}</h2><p class="document-lede">${escape(selected.summary)}</p>
      ${articleURL ? `<a class="button button-secondary" target="_blank" rel="noopener noreferrer" href="${escape(articleURL)}">${liveWiki ? "在飞书打开原件" : "查看原文"} ↗</a>` : ""}
      </header>${reader}${content}</article>`;
    const fullText = workspace.querySelector(".document-full-text");
    if (fullText) fullText.addEventListener("toggle", async () => {
      const body = fullText.querySelector("[data-document-markdown]");
      if (!fullText.open || body.dataset.state === "ready" || body.dataset.state === "loading") return;
      body.dataset.state = "loading";
      body.textContent = "正在读取原文…";
      try {
        const response = await fetch(body.dataset.documentMarkdown, { credentials: "same-origin", redirect: "error", cache: "no-cache" });
        const type = (response.headers.get("Content-Type") || "").split(";")[0].trim();
        if (!response.ok || !["text/plain", "text/markdown", "text/x-markdown"].includes(type)) throw new Error();
        body.textContent = await response.text();
        body.dataset.state = "ready";
      } catch {
        body.dataset.state = "failed";
        body.textContent = "暂时无法读取。可收起后重试，或点上方「查看原文」。";
      }
    });
    if (shouldFocus) focusDocumentHeading(workspace.querySelector(".document-reading h2"));
    else if (restoreFocus) workspace.querySelector(".document-reading h2").focus({ preventScroll: true });
  }

  async function loadDocuments(force) {
    if (documents.data && !force) { renderDocuments(); return; }
    if (documents.request) return;
    const request = new AbortController();
    documents.request = request;
    $("documents-reload").hidden = true;
    $("documents-status").textContent = "正在读取文档目录…";
    try {
      const data = await api("/api/workspace-docs", { signal: request.signal });
      if (request.signal.aborted) return;
      documents.data = list(data.items);
      if (!$("documents").hidden) renderDocuments();
    } catch (error) {
      if (request.signal.aborted || error.code === "unauthenticated") return;
      if (documents.data && !$("documents").hidden) renderDocuments();
      $("documents-status").textContent = "暂时无法读取原点文档。";
      $("documents-reload").hidden = false;
    } finally {
      if (documents.request === request) documents.request = null;
    }
  }

  const progressFields = {done: "近期进展", results: "成果与证据", blockers: "阻塞与协作", next: "下一步"};
  const researchFields = {overview: "研究大局", findings: "关键发现与证据", constraints: "共同瓶颈", priorities: "下一步验证"};

  function progressURL(value) {
    if (typeof value !== "string") return null;
    try {
      const url = new URL(value, location.origin + "/progress/");
      return url.origin === location.origin && (url.pathname === "/progress/" || url.pathname.startsWith("/progress/api/report-source/")) ? url.href : null;
    } catch { return null; }
  }

  function homeProgressFields(record, sources, labels = progressFields) {
    return Object.entries(labels).map(([field, title]) => {
      const items = list(record[field]);
      if (!items.length) return "";
      return `<div class="home-progress-field"><h4>${title}</h4><ul>${items.map((item) => {
        const refs = list(item.source_ids).map((id) => sources.get(id)).filter(Boolean);
        const links = refs.map((source) => {
          const url = progressURL(source.url);
          return url ? `<a href="${escape(url)}">${escape(source.title)}</a>` : "";
        }).filter(Boolean).join(" · ");
        return `<li>${escape(item.text)}${links ? `<div class="home-progress-sources">${links}</div>` : ""}</li>`;
      }).join("")}</ul></div>`;
    }).join("");
  }

  function renderHomeProgress(payload) {
    const doc = payload.document;
    const status = payload.status || {};
    const states = {running: "正在整理新记录", stale: "有新记录，等待整理", failed: "更新暂未完成", pending: "等待首次整理", disabled: "自动整理尚未启用"};
    const statusText = states[status.state];
    const link = $("home-team-link");
    link.href = "/progress/#team";
    link.querySelector("span").textContent = "查看整体与成员进展";
    if (!doc) {
      for (const id of ["home-progress-overview", "home-progress-members", "home-progress-direction-list", "home-progress-rhythm-chart"]) $(id).replaceChildren();
      $("home-progress-directions").hidden = true;
      $("home-progress-rhythm").hidden = true;
      $("home-team-status").textContent = statusText || "查看各成员研究记录";
      $("home-progress-status").textContent = (statusText || "正在准备研究总览") + "，可从完整进展查看已提交的日报和周报。";
      return;
    }
    const sources = new Map(list(doc.sources).map((source) => [source.id, source]));
    const counts = doc.counts || {};
    const hasBrief = Boolean(doc.research_brief);
    const brief = hasBrief ? doc.research_brief : doc.team || {};
    const labels = hasBrief ? researchFields : progressFields;
    const entries = list(doc.research_brief?.overview).concat(list(doc.team?.done), list(doc.team?.results));
    const heroText = entries[0]?.text || `${counts.active_members || 0} 位成员有近期记录`;
    $("home-team-status").textContent = heroText.length > 116 ? heroText.slice(0, 115) + "…" : heroText;
    $("home-progress-status").textContent = `${doc.period.from} 至 ${doc.period.to} · ${counts.members} 位成员 · ${counts.daily} 份日报、${counts.weekly} 份周报 · ${doc.engine || "DeepSeek"} · ${formatDate(doc.generated_at, true)}${statusText ? " · " + statusText : ""}`;
    const openedMembers = new Set([...$("home-progress-members").querySelectorAll("details[open]")].map((node) => node.dataset.member));
    const openedDirections = new Set([...$("home-progress-direction-list").querySelectorAll("details[open]")].map((node) => node.dataset.direction));
    const active = $("home-progress").contains(document.activeElement) ? document.activeElement : null;
    const focus = active ? {member: active.closest("[data-member]")?.dataset.member, direction: active.closest("[data-direction]")?.dataset.direction,
      href: active.getAttribute("href"), summary: active.tagName === "SUMMARY", team: Boolean(active.closest(".home-team-overview"))} : null;
    const teamOpen = $("home-progress-overview").querySelector("details")?.open ?? false;
    const overview = Object.entries(labels).map(([field, title]) => {
      const first = list(brief[field])[0];
      return first ? `<section><h3>${title}</h3><p>${escape(first.text)}</p></section>` : "";
    }).join("");
    $("home-progress-overview").innerHTML = `<div class="home-team-summary">${overview || '<p class="workspace-status">本期暂无可归纳的研究记录。</p>'}</div><details class="home-team-overview" ${teamOpen ? "open" : ""}><summary>展开整体进展与依据</summary>${homeProgressFields(brief, sources, labels)}</details>`;
    if (typeof window.renderReportRhythm === "function") {
      $("home-progress-rhythm").hidden = false;
      window.renderReportRhythm($("home-progress-rhythm-chart"), doc);
    }
    $("home-progress-members").innerHTML = list(doc.members).map((member) => {
      const headline = Object.keys(progressFields).map((field) => list(member[field])[0]?.text).find(Boolean)
        || (member.report_count ? "已有记录，尚无可归纳摘要" : "本期尚未收到研究报告");
      const short = headline.length > 96 ? headline.slice(0, 95) + "…" : headline;
      return `<details class="home-member-progress" data-member="${escape(member.id)}" ${openedMembers.has(member.id) ? "open" : ""}><summary><strong>${escape(member.name)}</strong><small>${member.report_count || 0} 份记录${member.last_report_at ? " · " + escape(member.last_report_at) : ""}</small><span>${escape(short)}</span></summary><div>${homeProgressFields(member, sources)}</div></details>`;
    }).join("");
    $("home-progress-directions").hidden = false;
    $("home-progress-direction-list").innerHTML = list(doc.directions).map((direction) => {
      const baselineURL = progressURL(direction.baseline?.url);
      return `<details data-direction="${escape(direction.id)}" ${openedDirections.has(direction.id) ? "open" : ""}><summary><strong>${escape(direction.title)}</strong><small>${direction.report_count ? direction.report_count + " 份相关报告" : "近期暂无对应报告"}</small></summary><div>${homeProgressFields(direction, sources)}${baselineURL ? `<a class="workspace-link" href="${escape(baselineURL)}">研究问题与既有基线 ↗</a>` : ""}</div></details>`;
    }).join("") + (Object.keys(progressFields).some((field) => list(doc.unassigned?.[field]).length) ? `<details><summary><strong>待归类工作</strong></summary><div>${homeProgressFields(doc.unassigned, sources)}</div></details>` : "");
    if (focus) {
      const scope = focus.member ? $("home-progress-members").querySelector(`[data-member="${CSS.escape(focus.member)}"]`)
        : focus.direction ? $("home-progress-direction-list").querySelector(`[data-direction="${CSS.escape(focus.direction)}"]`)
          : focus.team ? $("home-progress-overview").querySelector("details") : null;
      const target = focus.href ? [...(scope || $("home-progress")).querySelectorAll("a")].find((node) => node.getAttribute("href") === focus.href)
        : focus.summary ? scope?.querySelector("summary") : null;
      target?.focus({preventScroll: true});
    }
  }

  async function loadHome(force) {
    if (home.request || (home.loaded && !force)) return;
    const request = new AbortController();
    home.request = request;
    try {
      const data = await api("/progress/api/progress-digest", { signal: request.signal });
      if (request.signal.aborted) return;
      const signature = `${data.document?.fingerprint || ""}:${data.document?.revision || ""}:${data.status?.state || ""}`;
      if (signature !== home.signature) {
        renderHomeProgress(data);
        home.signature = signature;
      }
      home.loaded = true;
    } catch {
      if (!request.signal.aborted) {
        home.signature = null;
        $("home-progress-status").textContent = "暂时无法更新进展，可重试或进入完整进展查阅原始记录。";
      }
    } finally {
      if (home.request === request) home.request = null;
    }
  }

  function resetLibrary() {
    Object.assign(library, { theme: "", category: "", subcategory: "", query: "", page: 1 });
    $("library-query").value = "";
    renderLibrary();
  }

  for (const [target, key, attribute] of [["library-themes", "theme", "libraryTheme"], ["library-categories", "category", "libraryCategory"], ["library-subcategories", "subcategory", "librarySubcategory"]]) {
    $(target).addEventListener("click", (event) => {
      const trigger = event.target.closest("button");
      if (!trigger) return;
      library[key] = trigger.dataset[attribute];
      if (key === "theme") library.category = "";
      if (key !== "subcategory") library.subcategory = "";
      library.page = 1;
      renderLibrary();
      $(target).querySelector('[aria-pressed="true"]')?.focus({ preventScroll: true });
    });
  }
  $("library-query").addEventListener("input", (event) => {
    library.query = event.target.value;
    library.page = 1;
    renderLibrary();
  });
  $("library-reset").addEventListener("click", resetLibrary);
  $("library-reload").addEventListener("click", () => loadLibrary(true));
  $("documents-reload").addEventListener("click", () => loadDocuments(true));
  for (const [id, increment] of [["library-prev", -1], ["library-next", 1]]) {
    $(id).addEventListener("click", () => {
      library.page = Math.max(1, library.page + increment);
      renderLibrary();
      $("library-selection").scrollIntoView({ block: "nearest" });
    });
  }
  $("library-results").addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-library-item]");
    if (!trigger) return;
    const item = library.data?.items.find((candidate) => candidate.id === trigger.dataset.libraryItem);
    if (item) openLibraryItem(item, trigger);
  });
  $("close-library-dialog").addEventListener("click", () => $("library-dialog").close());
  $("library-dialog").addEventListener("close", () => activeDetailTrigger?.focus({ preventScroll: true }));
  $("library-dialog").addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-library-asset]");
    if (!trigger) return;
    $("library-dialog").close();
    openAsset(trigger.dataset.libraryAsset, activeDetailTrigger);
  });

  $("workspace-documents").addEventListener("click", (event) => {
    const link = event.target.closest(".document-index a");
    if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
    if (link.hash === location.hash) {
      event.preventDefault();
      focusDocumentHeading($("workspace-documents").querySelector(".document-reading h2"));
    } else documents.focusHash = link.hash;
  });
  $("workspace-documents").addEventListener("change", (event) => {
    if (!event.target.matches("[data-document-select]") || !event.target.value) return;
    documents.focusHash = `#documents/${encodeURIComponent(event.target.value)}`;
    location.hash = documents.focusHash;
  });

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && !$("overview").hidden) loadHome(true);
  });

  return {
    show(view, hash, legacyData, force = false) {
      clearInterval(home.timer);
      home.timer = null;
      const frame = $("workspace-documents").querySelector(".document-live iframe");
      if (view !== "documents" && frame) {
        frame.remove();
        documents.rendered = null;
      }
      if (view === "home") home.timer = setInterval(() => { if (!document.hidden) loadHome(true); }, 30_000);
      if (documents.focusHash !== `#${hash}`) documents.focusHash = null;
      if (view === "data-platform" && !legacyData) return showLibrary(hash, force);
      if (view === "documents") {
        const selection = hash.slice("documents/".length);
        try { documents.selected = decodeURIComponent(selection); } catch { documents.selected = null; }
        return loadDocuments(force);
      }
      if (view === "home") return loadHome(force);
    },
    clear() {
      for (const panel of [library, documents, home]) { panel.request?.abort(); panel.request = null; }
      library.data = documents.data = null;
      documents.focusHash = documents.rendered = null;
      home.loaded = false;
      home.signature = null;
      clearInterval(home.timer);
      for (const label of document.querySelectorAll("[data-library-count]")) label.textContent = "";
      for (const id of ["library-categories", "library-subcategories", "library-results", "workspace-documents", "library-dialog-content"]) $(id).replaceChildren();
      if ($("library-dialog").open) $("library-dialog").close();
      $("library-pager").hidden = true;
      $("home-team-status").textContent = "登录后查看团队进展";
      for (const id of ["home-progress-overview", "home-progress-members", "home-progress-direction-list", "home-progress-rhythm-chart"]) $(id).replaceChildren();
      $("home-progress-directions").hidden = true;
      $("home-progress-rhythm").hidden = true;
      $("home-progress-status").textContent = "登录后查看团队近期进展。";
      $("library-status").textContent = "登录后查看资料目录。";
      $("documents-status").textContent = "登录后查看原点文档。";
    },
  };
};
