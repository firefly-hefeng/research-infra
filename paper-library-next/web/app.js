const $ = (id) => document.getElementById(id);
const API_BASE = window.location.pathname.startsWith('/papers/') ? '/papers' : '';
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state = {papers: [], jobs: [], agent: {}}, category = '', tag = '', selected = null;
let toastTimer, searchTimer, readingPoll, readingPolling = false, readingRequest = null, renderedCardVersion = null;
const noteDrafts = new Map();
const readingSections = [
  ['background', '研究背景', '这项工作从哪里出发'],
  ['problem', '研究问题', '要解决什么，难点在哪里'],
  ['method', '方法详解', '核心思路与实现过程'],
  ['experiments', '实验设计', '数据、基线与评价条件'],
  ['results', '结果与分析', '收益、对照与适用条件'],
  ['discussion', '讨论与启发', '结论的边界与研究意义'],
  ['reproduction', '复现要点', '实现设置与尚缺的信息']
];
const hasReading = c => readingSections.some(([key]) => c.reading?.[key]);
const bibliographyState = data => ({...data, papers: (data.papers || []).map(p => {
  if (p.card || !p.bibliography) return p;
  const b = p.bibliography;
  return {...p, bibliography_only: true, card: {
    title: b.title, authors: b.authors || [], year: b.year, venue: b.venue || '', doi: b.doi || '',
    category: b.category || '文献题录', tags: b.tags || [], summary: b.summary || '资料说明待补充。',
    contributions: [], limitations: [], reading: {}, evidence: [], needs_review: true,
    review_reason: '题录继承既有整理索引；本轮未逐篇核验原文，不代表已生成精读卡片。',
    updated_at: b.imported_at,
  }};
})});

function externalURL(value) {
  try { const u = new URL(value); return ['http:', 'https:'].includes(u.protocol) && !u.username && !u.password ? u.href : ''; }
  catch { return ''; }
}
function rememberNote() { if (selected && $('notes')) noteDrafts.set(selected, $('notes').value); }
function toast(message) {
  // Native dialogs occupy the top layer; their feedback must live there too.
  const notice = $('toast');
  (document.querySelector('dialog[open]') || document.body).appendChild(notice);
  notice.textContent = message; notice.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => notice.hidden = true, 5000);
}
async function api(path, options = {}) {
  const response = await fetch(API_BASE + path, {...options, headers: {'Content-Type': 'application/json', 'X-Paper-Library': '1', ...(options.headers || {})}});
  const data = await response.json();
  if (response.status === 401) { if (!$('login').open) $('login').showModal(); throw new Error(data.error); }
  if (!response.ok) throw new Error(data.error || '请求失败');
  return data;
}
async function refresh(silent = false) {
  try {
    state = bibliographyState(await api('/api/state'));
    render();
    if ($('detail').open && selected && cardVersion(state.papers.find(p => p.id === selected)) !== renderedCardVersion) openPaper(selected, true);
    if (!silent) toast('论文库已刷新');
  } catch (error) { if (!$('login').open) toast(error.message); }
}
const ready = () => state.papers.filter(p => p.card);
const pending = () => state.papers.filter(p => !p.card);
const countBy = (items, fn) => { const result = {}; items.forEach(p => fn(p).forEach(x => result[x] = (result[x] || 0) + 1)); return Object.entries(result).sort((a,b) => b[1] - a[1] || a[0].localeCompare(b[0])); };
function render() {
  const papers = ready(), tags = countBy(papers, p => p.card.tags), topics = countBy(papers, p => [p.card.category]);
  $('stat-ready').innerHTML = `${papers.length}<small>条</small>`;
  $('stat-tags').innerHTML = `${tags.length}<small>个</small>`;
  $('stat-pending').innerHTML = `${pending().length}<small>篇</small>`;
  $('inbox-count').textContent = pending().length;
  $('management-count').textContent = `${pending().length} 篇待处理`;
  document.querySelector('.agent-state').classList.toggle('is-running', state.running);
  $('agent-label').textContent = state.running ? '正在整理' : !state.agent.configured ? '整理通道未配置' : state.agent.mode === 'api' ? '自定义 API' : state.agent.mode === 'agent' ? 'Agent' : state.agent.api_configured ? 'Agent 优先 · API 备用' : 'Agent · API 未配置';
  $('agent-caption').textContent = state.agent.enabled ? `每日 ${state.agent.time} · ${state.agent.timezone}` : '自动调度未启用';
  $('category').innerHTML = '<option value="">全部方向</option>' + topics.map(([name, n]) => `<option value="${esc(name)}">${esc(name)} · ${n}</option>`).join('');
  $('category').value = category;
  const year = $('year').value;
  const years = [...new Set(papers.map(p => p.card.year).filter(Boolean))].sort((a,b) => b-a);
  $('year').innerHTML = '<option value="">全部年份</option>' + years.map(y => `<option value="${y}">${y} 年</option>`).join('') + (papers.some(p => !p.card.year) ? '<option value="unknown">年份待核对</option>' : '');
  $('year').value = year;
  $('tag-cloud').innerHTML = tags.slice(0, 10).map(([name]) => `<button class="chip ${tag === name ? 'active' : ''}" data-tag="${esc(name)}">${esc(name)}</button>`).join('');
  $('inbox-path').textContent = $('guide-path').textContent = state.inbox;
  $('run').disabled = !state.agent.configured || state.running;
  $('run').textContent = state.running ? '正在整理…' : state.agent.configured ? '开始整理' : '请先配置整理方式';
  renderPapers(); renderInbox(); renderJobs();
}
function renderPapers() {
  const query = $('search').value.trim().toLowerCase();
  const year = $('year').value;
  let papers = ready().filter(p => (!$('favorites-only').checked || p.favorite) && (!category || p.card.category === category) && (!tag || p.card.tags.includes(tag)) && (!year || (year === 'unknown' ? !p.card.year : String(p.card.year) === year)));
  const terms = query.split(/\s+/).filter(Boolean);
  papers = papers.filter(p => {
    const haystack = [p.card.title, ...p.card.authors, p.card.summary, ...p.card.contributions, ...p.card.tags, p.card.venue, ...readingSections.map(([key]) => p.card.reading?.[key] || ''), p.notes].join(' ').toLowerCase();
    return terms.every(q => haystack.includes(q));
  });
  if ($('sort').value === 'year') papers.sort((a,b) => (b.card.year || 0) - (a.card.year || 0));
  if ($('sort').value === 'title') papers.sort((a,b) => a.card.title.localeCompare(b.card.title));
  $('section-title').innerHTML = `${$('favorites-only').checked ? '我的收藏' : category ? esc(category) : '全部论文'} <span>${papers.length}</span>`;
  $('clear-filters').hidden = !category && !tag && !year && !query && !$('favorites-only').checked;
  const summary = [$('favorites-only').checked && '仅看收藏', category, tag, year && (year === 'unknown' ? '年份待核对' : year + ' 年')].filter(Boolean);
  $('filter-summary').hidden = !summary.length;
  $('filter-summary').textContent = `当前筛选：${summary.join(' / ')} · ${papers.length} 篇论文`;
  $('papers').innerHTML = papers.map(p => {
    const c = p.card;
    return `<article class="paper-card"><div class="card-top"><span class="category-label">${esc(c.category)}</span><span class="card-year">${c.year || '年份待核对'}</span><button class="favorite ${p.favorite ? 'on' : ''}" data-favorite="${p.id}" aria-label="${p.favorite ? '取消收藏' : '收藏'}：${esc(c.title)}" aria-pressed="${p.favorite}">${p.favorite ? '★' : '☆'}</button></div><button class="card-title" data-open="${p.id}">${esc(c.title)}</button><div class="authors" title="${esc(c.authors.join(' · '))}">${esc(c.authors.join(' · ') || '作者待核对')}</div><p class="summary">${esc(c.reading?.takeaway || c.summary)}</p><div class="card-tags">${c.tags.slice(0, 3).map(t => `<button class="chip" data-tag="${esc(t)}">${esc(t)}</button>`).join('')}${c.tags.length > 3 ? `<span class="chip">+${c.tags.length - 3}</span>` : ''}</div><div class="card-publication"><span class="journal" title="${esc(c.venue || '出版信息待核对')}">${esc(c.venue || '出版信息待核对')}</span><span>${p.bibliography_only ? '导入题录' : hasReading(c) ? '详细解读' : '基础卡片'}</span></div><div class="card-bottom"><span class="${p.bibliography_only || p.status === 'review' || !p.available ? 'status-review' : 'status-ready'}">${!p.available ? '◌ 原件缺失' : p.bibliography_only ? '◌ 题录已导入 · 待原文核验' : p.status === 'review' ? '◌ 信息待核对' : '◦ 已整理'}</span><button data-open="${p.id}">阅读论文详情 <span>↗</span></button></div></article>`;
  }).join('') || `<div class="empty"><div class="empty-symbol">⌕</div><h3>${ready().length ? '没有找到匹配的论文' : '你的研究书架，等待第一篇论文'}</h3><p>${ready().length ? '试试其他关键词，或清除方向、标签与年份筛选。' : '点击“添加论文”，将 PDF 放入待整理区并完成整理。'}</p></div>`;
}
function renderInbox() {
  $('inbox-list').innerHTML = pending().map(p => `<div class="queue-item"><div><h3>${esc(p.filename)}</h3><p>${esc(p.error || '等待阅读、归类并生成论文卡片')}</p><p>${esc(p.source)}</p></div><span class="status-review">${p.status === 'error' ? '处理失败 · 可重试' : '等待整理'}</span></div>`).join('') || '<p class="queue-clear">✓ 暂无待整理论文</p>';
}
const date = value => value ? new Date(value).toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai', hour12: false}) : '—';
function renderJobs() {
  $('schedule-info').innerHTML = `<p class="panel-hint">${state.agent.enabled ? '每日 ' + esc(state.agent.time) + '（' + esc(state.agent.timezone) + '）自动整理' : '自动调度未启用'}${state.running ? ' · 正在整理中' : ''}</p>${!state.agent.configured ? '<p class="panel-hint">配置 Agent 或 API 后，可在这里查看处理结果。</p>' : ''}${state.scheduler_error ? `<p class="warning">${esc(state.scheduler_error)}</p>` : ''}`;
  $('job-count').textContent = state.jobs.length;
  const statuses = {completed: '已完成', partial: '部分完成', failed: '失败', running: '运行中', interrupted: '被中断'};
  $('jobs').innerHTML = state.jobs.map(j => `<article class="job"><h3>${j.result.task === 'reading' ? '详细解读' : '整理任务'} #${j.id} · ${statuses[j.status] || esc(j.status)}</h3><p>已整理 ${j.result.completed || 0} 篇 · 失败 ${j.result.failed || 0} 篇</p>${j.result.providers ? `<p>Agent ${j.result.providers.agent} 篇 · API ${j.result.providers.api} 篇 · 自动切换 ${j.result.fallbacks || 0} 次 · 输出修正 ${j.result.repairs || 0} 次</p>` : ''}${(j.result.items || []).filter(x => x.attempts.some(a => a.error)).map(x => `<p>${esc(x.filename)}：${x.attempts.map(a => `${a.provider === 'api' ? 'API' : 'Agent'}${a.number === 2 ? '（修正）' : ''} ${a.error ? esc(a.error) : '卡片校验通过'}`).join(' → ')}</p>`).join('')}<p>${(j.result.errors || []).map(e => esc((e.filename || '') + ' ' + e.message)).join('<br>')}</p>${j.result.log_file ? `<p>日志文件：${esc(j.result.log_file)}</p>` : ''}${j.result.log_warning ? `<p>${esc(j.result.log_warning)}</p>` : ''}<small>${date(j.started)} → ${date(j.finished)} · 北京时间</small></article>`).join('') || '<p class="panel-hint">暂无自动整理记录。</p>';
}
const cardVersion = p => p?.card ? `${p.id}:${p.card.updated_at || p.updated}` : null;
function openPaper(id, keepPosition = false) {
  const p = state.papers.find(p => p.id === id);
  if (!p?.card) return;
  rememberNote();
  const scroll = keepPosition && selected === id ? $('detail').scrollTop : 0;
  selected = id;
  renderedCardVersion = cardVersion(p);
  const c = p.card, r = c.reading || {}, pdf = `${API_BASE}/api/papers/${id}/pdf`, sections = [];
  const fieldNames = {title: '标题', authors: '作者', year: '年份', venue: '会议 / 期刊', summary: '核心摘要', contributions: '主要贡献', limitations: '适用范围与局限', doi: 'DOI', 'reading.takeaway': '研究速览', 'reading.result_table': '实验对照', 'reading.resources': '研究资源', ...Object.fromEntries(readingSections.map(([key, title]) => ['reading.' + key, title]))};
  const paragraphs = value => String(value).split(/\n\s*\n/).filter(x => x.trim()).map(x => `<p class="reading-paragraph">${esc(x)}</p>`).join('');
  const citations = field => {
    const refs = c.evidence.map((e, i) => ({...e, index: i + 1})).filter(e => e.field === field);
    return refs.length ? `<div class="section-sources"><span>原文依据</span>${refs.map(e => `<button data-evidence="${e.index}" title="查看第 ${e.index} 条原文依据">[${e.index}] 第 ${e.page} 页</button>`).join('')}</div>` : '';
  };
  const section = (key, title, subtitle, body, field) => {
    sections.push([key, title]);
    return `<section class="detail-section" id="reader-${key}" tabindex="-1"><div class="reading-section-heading"><span>${String(sections.length).padStart(2, '0')}</span><div><h3>${esc(title)}</h3>${subtitle ? `<p>${esc(subtitle)}</p>` : ''}</div></div>${body}${field ? citations(field) : ''}</section>`;
  };
  let article = section('summary', p.bibliography_only ? '已有资料说明' : '核心摘要', p.bibliography_only ? '来自已有文献索引，保留原有说明与证据边界' : '', paragraphs(c.summary), 'summary');
  if (c.contributions.length) article += section('contributions', '主要贡献', '这篇论文带来了什么', `<ol class="contribution-list">${c.contributions.map(x => `<li>${esc(x)}</li>`).join('')}</ol>`, 'contributions');
  readingSections.forEach(([key, title, subtitle]) => {
    if (r[key]) article += section(key, title, subtitle, paragraphs(r[key]), 'reading.' + key);
    if (key === 'results' && r.result_table?.rows?.length) {
      const t = r.result_table;
      article += section('result-table', '实验对照', '指标与结论需结合原文实验条件阅读', `<div class="results-table" role="region" aria-label="实验结果表" tabindex="0"><table><caption>${esc(t.caption || '论文报告的实验结果')}</caption><thead><tr>${t.columns.map(x => `<th scope="col">${esc(x)}</th>`).join('')}</tr></thead><tbody>${t.rows.map(row => `<tr>${row.map((x, i) => i === 0 ? `<th scope="row">${esc(x)}</th>` : `<td>${esc(x)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`, 'reading.result_table');
    }
  });
  if (c.limitations.length) article += section('limitations', '适用范围与局限', '哪些结论还不能下', `<ul class="limitation-list">${c.limitations.map(x => `<li>${esc(x)}</li>`).join('')}</ul>`, 'limitations');
  if (r.resources?.length) article += section('resources', '开源与研究资源', '论文提供的链接；可达性、许可证与复现结果尚未核验', `<div class="resource-list">${r.resources.map(x => { const url = externalURL(x.url); return url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer"><span class="resource-kind">${{code: '代码', data: '数据', project: '项目', other: '资源'}[x.kind] || '资源'}</span><span>${esc(x.label)}<small>${esc(new URL(url).hostname)}</small></span><span aria-hidden="true">↗</span></a>` : `<p>${esc(x.label)} · 链接不可用</p>`; }).join('')}</div>`, 'reading.resources');
  if (c.year_note) article += section('version', '版本说明', '', paragraphs(c.year_note));
  if (!p.bibliography_only) article += section('evidence', '原文依据', '点击页码回到 PDF 核对；引文存在不代表解读必然正确', `<details id="evidence-details"><summary>${c.evidence.length} 条可追溯引用 <span>展开原文摘录</span></summary>${c.evidence.map((e, i) => `<div class="evidence" id="evidence-${i + 1}" tabindex="-1"><div><span class="evidence-index">[${i + 1}]</span> ${esc(fieldNames[e.field] || e.field)}<a href="${pdf}#page=${e.page}" target="_blank" rel="noopener">PDF 第 ${e.page} 页 ↗</a></div><blockquote>${esc(e.quote)}</blockquote></div>`).join('')}</details>`);
  if (p.bibliography_only) article += section('bibliography', '题录来源与核验边界', '记录来源，不把既有摘要伪装成原文引文', `<ul class="bibliography-provenance">${(p.bibliography.provenance || []).map(source => `<li><strong>${esc(source.label)}</strong>${source.record_id ? `<span>原记录 ${esc(source.record_id)}</span>` : ''}<code>来源 SHA-256：${esc(source.sha256)}</code></li>`).join('')}</ul><p class="reading-paragraph">按 PDF 字节哈希去重，相同原件不会重复入库；不同版本与补充材料仍分别记录。此批只开放题录，原件保存在受控文献库，需按团队权限访问。</p>`);
  article += section('notes', '我的阅读笔记', '记录与你的研究有关的启发、疑问与后续计划', `<textarea id="notes" aria-label="阅读笔记" placeholder="读到这里，你想到了什么？" maxlength="20000">${esc(noteDrafts.has(id) ? noteDrafts.get(id) : p.notes)}</textarea><div class="note-footer"><button class="secondary" id="save-notes">保存笔记</button><span id="notes-status" role="status">${noteDrafts.has(id) && noteDrafts.get(id) !== p.notes ? '有未保存的修改' : '仅你手动保存后写入论文库'}</span></div>`);
  const textLength = [c.summary, ...c.contributions, ...c.limitations, ...readingSections.map(([key]) => r[key] || '')].join('').length;
  const notice = p.bibliography_only ? '这是从已有整理索引导入的题录，可搜索、收藏、做笔记；未启动模型精读，原文访问需按团队授权。' : hasReading(c) ? '根据论文原文生成的分节解读，可结合下方引用核对。' : '这篇论文目前保存的是基础卡片。手动生成详细解读后，这里会补充研究背景、方法、实验和结果分析。';
  $('detail-content').innerHTML = `<header class="reader-header"><div class="eyebrow">PAPER READING <span> / </span> ${esc(c.category)}</div><h2 id="detail-title">${esc(c.title)}</h2><p class="detail-authors">${esc(c.authors.join(' · ') || '作者待核对')}</p><div class="reader-byline"><span>${esc(c.venue || '出版信息待核对')}</span><span>${c.year || '年份待核对'}</span><span>约 ${Math.max(1, Math.ceil(textLength / 500))} 分钟阅读</span><span>${p.bibliography_only ? '已有索引题录' : hasReading(c) ? '含详细解读' : '基础卡片'}</span></div><div class="detail-meta">${c.tags.map(t => `<button class="chip" data-detail-tag="${esc(t)}">${esc(t)}</button>`).join('')}</div><div class="detail-actions">${p.fulltext_available !== false ? `<a class="primary" href="${pdf}" target="_blank" rel="noopener">阅读 PDF 原文 ↗</a><a class="secondary" href="${pdf}" download="${esc(p.filename)}">下载原件 ↓</a>` : `<span class="bibliography-access">原件按团队权限访问</span>`}<button class="secondary" data-favorite="${id}">${p.favorite ? '★ 已收藏' : '☆ 收藏论文'}</button></div>${c.needs_review ? `<div class="warning">信息待核对：${esc(c.review_reason)}</div>` : ''}${!p.available ? '<div class="warning">PDF 原件缺失，请检查服务器文件目录。</div>' : ''}</header>
    <div class="reader-columns"><main class="reader-article">${r.takeaway ? `<div class="reading-takeaway"><span>研究速览</span><p>${esc(r.takeaway)}</p>${citations('reading.takeaway')}</div>` : ''}<div class="reading-update"><div><strong>${p.bibliography_only ? '题录导入状态' : hasReading(c) ? '论文深度解读' : '展开这篇论文'}</strong><p>${notice}</p><p id="reading-status" role="status"></p></div><button class="secondary" id="generate-reading" ${p.bibliography_only ? 'hidden' : ''} ${state.running || !state.agent.configured || !p.available ? 'disabled' : ''}>${hasReading(c) ? '更新详细解读' : '生成详细解读'}</button></div>${article}</main>
    <aside class="reader-aside"><div class="reader-aside-inner"><nav class="reader-toc" aria-label="本篇阅读目录"><p>本篇目录 <span>${sections.length}</span></p>${sections.map(([key, title], i) => `<button data-section="reader-${key}"><span>${String(i + 1).padStart(2, '0')}</span>${esc(title)}</button>`).join('')}</nav><div class="reader-facts"><h3>论文档案</h3><dl><dt>研究方向</dt><dd>${esc(c.category)}</dd><dt>发表年份</dt><dd>${c.year || '待核对'}</dd><dt>引用依据</dt><dd>${p.bibliography_only ? '既有文献索引 · 待原文核验' : `${c.evidence.length} 条原文摘录`}</dd>${c.doi ? `<dt>DOI</dt><dd><a href="https://doi.org/${esc(encodeURIComponent(c.doi))}" target="_blank" rel="noopener noreferrer">${esc(c.doi)} ↗</a></dd>` : ''}<dt>卡片更新</dt><dd>${date(c.updated_at || p.updated)}</dd></dl><details><summary>归档信息</summary><p>文件：${esc(p.filename)}</p>${!p.bibliography_only ? `<p>位置：${esc(p.pdf)}</p>` : ''}<p>SHA-256：${id}</p></details></div></div></aside></div>`;
  if (!$('detail').open) $('detail').showModal();
  $('detail').scrollTop = scroll;
  updateReadingStatus();
  if (state.running) startReadingPoll();
}
function updateReadingStatus() {
  if (!$('detail').open || !selected || !$('reading-status')) return;
  const p = state.papers.find(p => p.id === selected);
  if (p?.bibliography_only) { $('generate-reading').hidden = true; $('reading-status').textContent = '未加入自动精读队列；题录与已核验卡片分开保存。'; return; }
  const job = state.jobs.find(j => j.result.task === 'reading' && j.result.paper_ids?.includes(selected));
  const busy = state.running || readingRequest === selected;
  $('generate-reading').disabled = busy || !state.agent.configured || !p?.available;
  $('generate-reading').textContent = busy && (job?.status === 'running' || readingRequest === selected) ? '正在生成…' : hasReading(p.card) ? '更新详细解读' : '生成详细解读';
  $('reading-status').textContent = busy ? '整理任务进行中，可以继续阅读；完成后详情会自动更新。' : job?.status === 'failed' ? '上次生成未完成，原有内容已保留。' + (job.result.errors?.[0]?.message || '可在整理记录中查看原因并重试。') : !p?.available ? '原件缺失，暂时无法补充解读。' : !state.agent.configured ? '请先在论文库的整理设置中配置 Agent 或 API。' : '仅在点击后调用当前配置的 Agent / API，处理这一篇论文。';
}
function startReadingPoll() {
  if (readingPoll) return;
  readingPoll = setInterval(async () => {
    if (readingPolling) return;
    readingPolling = true;
    try {
      state = bibliographyState(await api('/api/state'));
      render();
      if ($('detail').open && cardVersion(state.papers.find(p => p.id === selected)) !== renderedCardVersion) openPaper(selected, true);
      updateReadingStatus();
      if (!state.running) { clearInterval(readingPoll); readingPoll = null; }
    } catch (e) { toast(e.message); clearInterval(readingPoll); readingPoll = null; }
    finally { readingPolling = false; }
  }, 2500);
}
document.addEventListener('click', async event => {
  const b = event.target.closest('button'); if (!b) return;
  try {
    if (b.dataset.tag) { tag = tag === b.dataset.tag ? '' : b.dataset.tag; render(); }
    if (b.dataset.detailTag) { tag = b.dataset.detailTag; category = ''; $('detail').close(); render(); }
    if (b.dataset.open) openPaper(b.dataset.open);
    if (b.dataset.section || b.dataset.evidence) {
      if (b.dataset.evidence) $('evidence-details').open = true;
      const target = $(b.dataset.section || 'evidence-' + b.dataset.evidence);
      target?.focus({preventScroll: true});
      target?.scrollIntoView({behavior: 'smooth', block: 'start'});
      document.querySelectorAll('[data-section]').forEach(x => x.classList.toggle('active', x === b));
    }
    if (b.id === 'generate-reading') {
      b.disabled = true;
      readingRequest = selected;
      updateReadingStatus();
      try {
        await api(`/api/papers/${selected}/reading`, {method: 'POST', body: '{}'});
        toast('已开始生成这篇论文的详细解读');
        await refresh(true);
        startReadingPoll();
      } finally { readingRequest = null; updateReadingStatus(); }
    }
    if (b.dataset.favorite) {
      const p = state.papers.find(p => p.id === b.dataset.favorite);
      b.disabled = true;
      await api(`/api/papers/${p.id}`, {method: 'PATCH', body: JSON.stringify({favorite: !p.favorite})});
      await refresh(true);
      if ($('detail').open && selected === p.id) openPaper(p.id, true);
    }
    if (b.id === 'save-notes') {
      const paperId = selected, value = $('notes').value;
      b.disabled = true;
      await api(`/api/papers/${paperId}`, {method: 'PATCH', body: JSON.stringify({notes: value})});
      noteDrafts.set(paperId, value);
      await refresh(true);
      if (selected === paperId && $('notes-status')) $('notes-status').textContent = $('notes').value === value ? '已保存' : '有未保存的修改';
      b.disabled = false;
      toast('阅读笔记已保存');
    }
  } catch (e) { toast(e.message); b.disabled = false; }
});
$('detail').addEventListener('close', () => { rememberNote(); });
$('detail').addEventListener('input', e => { if (e.target.id === 'notes') { noteDrafts.set(selected, e.target.value); $('notes-status').textContent = '有未保存的修改'; } });
$('search').addEventListener('input', () => {clearTimeout(searchTimer); searchTimer = setTimeout(renderPapers, 120);});
$('year').onchange = $('sort').onchange = $('favorites-only').onchange = renderPapers;
$('category').onchange = () => { category = $('category').value; renderPapers(); };
$('clear-filters').onclick = () => {category = ''; tag = ''; $('year').value = ''; $('search').value = ''; $('favorites-only').checked = false; render();};
$('grid-view').onclick = () => {$('papers').classList.remove('list'); $('grid-view').classList.add('selected'); $('list-view').classList.remove('selected'); $('grid-view').setAttribute('aria-pressed', 'true'); $('list-view').setAttribute('aria-pressed', 'false');};
$('list-view').onclick = () => {$('papers').classList.add('list'); $('list-view').classList.add('selected'); $('grid-view').classList.remove('selected'); $('grid-view').setAttribute('aria-pressed', 'false'); $('list-view').setAttribute('aria-pressed', 'true');};
$('guide-button').onclick = () => $('guide').showModal();
$('close-guide').onclick = () => $('guide').close(); $('close-detail').onclick = () => $('detail').close();
$('refresh').onclick = () => refresh();
$('copy-path').onclick = async () => {try {await navigator.clipboard.writeText(state.inbox); toast('路径已复制');} catch {toast('请手动复制上方路径');}};
$('scan').onclick = async () => { $('scan').disabled = true; try {const r = await api('/api/scan', {method:'POST',body:'{}'}); await refresh(true); toast(`发现 ${r.added} 篇新论文，归档 ${r.duplicates} 份重复文件${r.skipped.length ? '；' + r.skipped.join('；') : ''}`);} catch(e){toast(e.message);} finally {$('scan').disabled = false;} };
$('run').onclick = async () => {try {await api('/api/run', {method:'POST',body:'{}'}); toast('整理任务已启动'); await refresh(true);} catch(e){toast(e.message);}};
$('login-form').onsubmit = async e => {e.preventDefault(); try {await api('/api/login', {method:'POST',body:JSON.stringify({password:$('password').value})}); $('password').value=''; $('login').close(); await refresh(true);} catch(error){$('login-error').textContent=error.message;}};
$('login').addEventListener('cancel', e => e.preventDefault());
document.addEventListener('keydown', e => {if (e.key === '/' && !['INPUT','TEXTAREA'].includes(document.activeElement.tagName) && !$('detail').open && !$('guide').open && !$('login').open && !($('management').open && $('provider-settings').open)) {e.preventDefault(); $('search').focus();}});
setInterval(() => {if (!$('login').open && !$('detail').open && !document.hidden) refresh(true);}, 30000);
refresh(true);

function describeProvider() {
  const mode = $('provider-mode').value;
  $('provider-description').textContent = mode === 'auto' ? '先尝试 Agent；未接入、超时、调用失败或卡片校验失败时，自动改用已配置的 API。每篇论文只归档一次。' : mode === 'agent' ? '只调用服务器上的 Agent，失败后保留论文等待重试。' : '直接调用自定义 API，使用同一份 skill 生成并校验卡片。';
}
async function loadProviderSettings() {
  try {
    const c = await api('/api/settings');
    $('provider-mode').value = c.mode;
    $('api-base-url').value = c.api_base_url;
    $('api-model').value = c.api_model;
    $('api-key').value = '';
    $('clear-api-key').checked = false;
    $('api-key-status').textContent = c.api_key_set ? '已保存密钥 · 留空可保留' : '尚未设置密钥（无鉴权的本地服务可留空）';
    $('api-timeout').value = c.api_timeout;
    $('agent-timeout').value = c.agent_timeout;
    $('api-json-mode').checked = c.api_json_mode;
    $('agent-config-status').textContent = c.agent_error || (c.agent_configured ? 'Agent 命令已配置，实际可用性以任务结果为准。' : 'Agent 未配置；自动模式下可直接使用已配置的 API。');
    $('settings-status').textContent = '';
    describeProvider();
  } catch (error) { $('settings-status').textContent = error.message; }
}
$('provider-settings').addEventListener('toggle', () => {
  if ($('provider-settings').open) loadProviderSettings();
  else $('api-key').value = '';
});
$('settings-button').onclick = () => { $('management').open = true; $('provider-settings').open = true; $('provider-settings').scrollIntoView({behavior: 'smooth', block: 'start'}); };
$('provider-mode').onchange = describeProvider;
$('provider-form').onsubmit = async event => {
  event.preventDefault();
  const payload = {
    mode: $('provider-mode').value, api_base_url: $('api-base-url').value.trim(),
    api_model: $('api-model').value.trim(), api_key: $('api-key').value,
    clear_api_key: $('clear-api-key').checked, api_json_mode: $('api-json-mode').checked,
    api_timeout: Number($('api-timeout').value), agent_timeout: Number($('agent-timeout').value)
  };
  if (payload.mode === 'api' && (!payload.api_base_url || !payload.api_model)) {
    $('settings-status').textContent = '请填写 API Base URL 和模型名称'; return;
  }
  $('save-provider').disabled = true;
  try {
    const c = await api('/api/settings', {method: 'PATCH', body: JSON.stringify(payload)});
    await loadProviderSettings();
    $('settings-status').textContent = c.configured ? '已保存，对下一批整理生效' : '已保存，请继续配置可用的整理通道';
    await refresh(true);
  } catch (error) { $('settings-status').textContent = error.message; }
  finally { $('save-provider').disabled = false; }
};
