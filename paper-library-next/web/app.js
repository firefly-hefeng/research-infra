const $ = (id) => document.getElementById(id);
const API_BASE = window.location.pathname.startsWith('/papers/') ? '/papers' : '';
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state = {papers: [], jobs: [], agent: {}}, category = '', tag = '', selected = null;
let pageView = 'discover', recommendationIds = [], routeInitialized = false;
const RECOMMENDATION_LIMIT = 3;
const PAGE_SIZE = 12;
let currentPage = 1, pageCount = 1;
let providerRequest = 0, providerLoaded = false, providerBusy = false, providerSavePromise = null;
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
    if (routeInitialized) render(); else applyRoute();
    if ($('detail').open && selected && cardVersion(state.papers.find(p => p.id === selected)) !== renderedCardVersion) openPaper(selected, true);
    if (!silent) toast('论文库已刷新');
  } catch (error) { if (!$('login').open) toast(error.message); }
}
const ready = () => state.papers.filter(p => p.card);
const pending = () => state.papers.filter(p => !p.card);
const countBy = (items, fn) => {
  const counts = new Map();
  items.forEach(p => new Set(fn(p)).forEach(x => counts.set(x, (counts.get(x) || 0) + 1)));
  return [...counts].sort((a,b) => b[1] - a[1] || a[0].localeCompare(b[0]));
};
function readRoute(hash = window.location.hash || '') {
  const [path, query = ''] = hash.replace(/^#/, '').split('?');
  if (path === 'workspace') return {view: 'workspace'};
  if (!['catalog', 'library-view', 'favorites'].includes(path)) return {view: 'discover'};
  const params = new URLSearchParams(query);
  const page = Number(params.get('page'));
  return {view: 'catalog', filters: {
    category: params.get('category') || '', tag: params.get('tag') || '', query: params.get('q') || '',
    year: params.get('year') || '', favorites: path === 'favorites' || params.get('favorites') === '1',
    sort: ['year', 'title'].includes(params.get('sort')) ? params.get('sort') : 'newest',
    page: Number.isSafeInteger(page) && page > 0 ? page : 1
  }};
}
function catalogHash(filters = {}) {
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries({category: filters.category, tag: filters.tag, q: filters.query,
    year: filters.year, favorites: filters.favorites ? '1' : '', sort: filters.sort === 'newest' ? '' : filters.sort,
    page: Number.isSafeInteger(filters.page) && filters.page > 1 ? filters.page : ''})) {
    if (value) params.set(name, value);
  }
  return '#catalog' + (params.size ? '?' + params.toString() : '');
}
function currentFilters() {
  return {category, tag, query: $('search').value, year: $('year').value,
    favorites: $('favorites-only').checked, sort: $('sort').value || 'newest', page: currentPage};
}
function navigateCatalog(filters = {}, replace = false, scroll = true) {
  const hash = catalogHash(filters);
  if (window.location.hash !== hash) window.history[replace ? 'replaceState' : 'pushState'](null, '', hash);
  applyRoute(scroll);
}
function applyRoute(scroll = false) {
  clearTimeout(searchTimer);
  const route = readRoute();
  routeInitialized = true;
  pageView = route.view;
  if ($('detail').open) { rememberNote(); $('detail').close(); }
  category = route.filters?.category || '';
  tag = route.filters?.tag || '';
  currentPage = route.filters?.page || 1;
  render(route.filters || {query: '', year: '', favorites: false, sort: 'newest'});
  if (scroll) {
    const target = $(pageView === 'discover' ? 'discovery-view' : pageView === 'workspace' ? 'management' : 'section-title');
    target.setAttribute('tabindex', '-1');
    target.focus({preventScroll: true});
    $(pageView === 'discover' ? 'discovery-view' : pageView === 'workspace' ? 'management' : 'library-view').scrollIntoView({block: 'start', behavior: 'instant'});
  }
}
function recommendedPapers(reshuffle = false) {
  const papers = ready(), byId = new Map(papers.map(p => [p.id, p]));
  const previous = recommendationIds;
  let ids = reshuffle ? [] : previous.filter(id => byId.has(id));
  const pool = papers.filter(p => !ids.includes(p.id));
  for (let i = pool.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [pool[i], pool[j]] = [pool[j], pool[i]];
  }
  ids = [...ids, ...pool.map(p => p.id)].slice(0, RECOMMENDATION_LIMIT);
  // A requested new batch should include something new when the library allows it.
  if (reshuffle && papers.length > RECOMMENDATION_LIMIT && ids.every(id => previous.includes(id))) {
    ids[ids.length - 1] = pool.find(p => !previous.includes(p.id)).id;
  }
  recommendationIds = ids;
  return ids.map(id => byId.get(id));
}
// Category introductions describe the scope of the collection, not verified findings.
const CATEGORY_DESCRIPTIONS = Object.freeze({
  '关联研究_不计音频核心': '收录访谈转写、语言标记及相关疾病研究，提供语义与方法参考；不计入纯音频抑郁识别的核心证据。',
  '临床验证与纵向追踪': '关注临床队列、重复测量与治疗过程，考察语音标记在不同人群中的适用性，以及随症状变化的表现。',
  '音文与视听融合': '联合语音、文本、面部与视频线索，研究跨模态对齐和信息融合，用于抑郁识别与严重度估计。',
  '采集协议与基础工具': '汇集录音采集规范、基础语音模型、训练工具与统计方法，为实验设计、数据处理和结果核对提供参考。',
  '跨域泛化与可信评估': '关注跨语料、跨语言与跨人群迁移，检查说话人泄漏、录音混杂、模型选择偏差及预测可靠性。',
  '数据集Bench与算法竞赛': '收录抑郁语音及多模态数据集、公开挑战赛和参赛方法，便于查找任务定义、标签、基线与评测协议。',
  '深度学习与预训练音频': '关注深度网络、自监督语音表征与长序列建模，研究如何提取音频线索，并汇总为个体层面的判断。',
  '声学特征与病理机制': '围绕韵律、声谱、声门与构音协调等特征，探索语音变化与抑郁症状、精神运动及发声机制的联系。',
  '言语机制': '关注反刍思维、情绪表达、叙事身份与语言互动，探索表达方式、治疗关系和心理变化之间的联系。',
  '对话交互': '汇集心理健康聊天机器人、情感支持智能体及用户体验研究，关注共情互动、治疗关系与使用效果评估。',
  '传统特征与机器学习': '以手工声学特征、统计表征和传统分类回归方法为主，比较特征选择、归一化与模型设计的作用。',
  '音乐疗法': '收录即兴演奏、音乐聆听、团体节奏等干预研究与证据汇总，关注干预形式、适用人群和心理健康结局。',
  '综述与证据综合': '汇总语音抑郁评估与精神健康语音分析的综述和元分析，梳理方法、数据条件、证据质量及临床应用边界。',
  '安全监管': '关注心理健康 AI 的风险识别、不当回应与污名问题，并收录数字疗法监管资料，帮助核对使用边界。',
  '心理LLM': '收录面向心理理解、共情支持与咨询对话的大语言模型，关注训练数据、专业知识、推理能力与模型评测。',
  '治疗对话策略': '研究动机访谈、情感支持与个性化咨询中的策略规划，关注倾听、反映、回应生成及共情与安全的平衡。',
  '歌唱干预': '关注社区合唱与团体歌唱在老年人、产后人群等场景的应用，收录试验方案、效果评估和实施成本研究。',
  '机制': '现有资料侧重音乐干预的心理生理机制，围绕奖赏加工、快感缺失、疼痛体验与神经调节展开研究。',
  '基准与数据集': '收录心理咨询与情感支持对话的数据集、专家评测和对抗基准，用于核对语言模型的对话质量与安全表现。',
  '朗读言语': '关注共享朗读、团体阅读与书目疗法，探索文学参与、情绪表达和健康体验，并比较干预研究的评估方式。',
  '数字疗法': '现有资料聚焦通过自动化对话实施心理干预的研究，关注认知行为治疗等内容及随机对照试验中的效果评估。',
  '危机干预': '收录文本危机咨询、自杀风险识别与干预聊天机器人研究，关注风险发现、响应流程和用户体验评估。',
  '中文研究': '收录阅读疗法及养老院团体音乐干预的研究，帮助了解大学生与老年人群的干预设计和评估场景。',
  '综述': '现有资料聚焦心理健康与心理治疗中的大语言模型，梳理咨询场景、智能体架构、评测框架和研究方向。',
  '通用方法支撑': '收录自适应实验设计与贝叶斯推断等通用方法，为研究设计提供背景参考，不作为抑郁语音识别的直接证据。',
  '医疗器械与监管': '收录抑郁症状辅助治疗软件的注册技术审评资料，便于查阅产品用途、申报信息与技术审评要求。',
  '语言模型': '关注语言模型的结构、预训练、指令微调与评测，梳理模型如何理解和生成文本，以及不同训练方法的适用条件。',
  '数据选择': '研究训练与微调数据的筛选、采样和混合策略，比较数据质量、多样性、模型效果与计算成本之间的关系。',
  '表征学习': '关注模型如何学习有用的特征表示，涵盖自监督学习、表示质量评估与迁移能力，帮助理解特征与下游任务的联系。',
  '泛化理论': '从理论角度研究训练表现如何延伸到新数据，关注模型、数据分布与任务结构对泛化误差和学习行为的影响。',
  '核方法': '收录核学习、核岭回归与随机近似方法，关注相似性建模、统计保证及大规模计算中的效率与精度取舍。',
});
function categoryDescription(name) {
  return Object.hasOwn(CATEGORY_DESCRIPTIONS, name) ? CATEGORY_DESCRIPTIONS[name] :
    `收录与“${name}”相关的研究文献，可结合论文摘要、原文与阅读笔记，了解具体方法和适用范围。`;
}
function renderDiscovery() {
  const papers = ready(), recommendations = recommendedPapers();
  const topics = countBy(papers, p => [p.card.category]);
  $('recommendation-count').textContent = recommendations.length;
  $('recommendation-note').textContent = '从已收录文献中随机选取，点击“换一批”探索更多论文。';
  $('shuffle-recommendations').disabled = papers.length <= RECOMMENDATION_LIMIT;
  $('shuffle-recommendations').title = papers.length <= RECOMMENDATION_LIMIT ? '已展示全部可推荐论文' : '随机发现另一批论文';
  $('recommended-papers').innerHTML = recommendations.map(p => paperCard(p, true)).join('') ||
    '<div class="empty"><div class="empty-symbol">◇</div><h3>等待第一篇推荐论文</h3><p>论文收录后会在这里随机展示。点击“添加论文”开始建立你的文献库。</p></div>';
  $('category-count').textContent = topics.length;
  $('category-grid').innerHTML = topics.map(([name, count], index) => {
    const members = papers.filter(p => p.card.category === name);
    const visual = topicVisual(name);
    const tags = countBy(members, p => p.card.tags).filter(([tag]) => tag !== name).slice(0, 3);
    return `<a class="category-card ${visual.tone}" href="${esc(catalogHash({category: name}))}" aria-label="${esc(name)}，${count} 篇论文" aria-describedby="category-description-${index}"><span class="category-icon" aria-hidden="true"><svg class="icon"><use href="#${visual.icon}"/></svg></span><div class="category-copy"><h3>${esc(name)} <span class="category-card-count">${count} 篇</span></h3><p id="category-description-${index}" class="category-description">${esc(categoryDescription(name))}</p>${tags.length ? `<div class="category-tags">${tags.map(([t]) => `<span>${esc(t)}</span>`).join('')}</div>` : ''}</div><span class="category-arrow" aria-hidden="true">↗</span></a>`;
  }).join('') || '<div class="empty"><h3>分类将随论文一起出现</h3><p>这里按论文现有分类自动汇总，不需要另行建立目录。</p></div>';
}
function render(routeFilters = null) {
  const papers = ready(), tags = countBy(papers, p => p.card.tags), topics = countBy(papers, p => [p.card.category]);
  $('stat-ready').innerHTML = `${papers.length}<small>条</small>`;
  $('stat-categories').innerHTML = `${topics.length}<small>个</small>`;
  $('stat-tags').innerHTML = `${tags.length}<small>个</small>`;
  $('stat-pending').innerHTML = `${pending().length}<small>篇</small>`;
  $('inbox-count').textContent = pending().length;
  $('management-count').textContent = `${pending().length} 篇待处理`;
  $('nav-all-count').textContent = papers.length;
  $('nav-favorite-count').textContent = papers.filter(p => p.favorite).length;
  $('nav-pending-count').textContent = pending().length;
  document.querySelector('.agent-state').classList.toggle('is-running', state.running);
  $('agent-label').textContent = state.running ? '正在整理' : !state.agent.configured ? '整理通道未配置' : state.agent.mode === 'api' ? '自定义 API' : state.agent.mode === 'agent' ? 'Agent' : state.agent.api_configured ? 'Agent 优先 · API 备用' : 'Agent · API 未配置';
  $('agent-caption').textContent = state.agent.enabled ? `每日 ${state.agent.time} · ${state.agent.timezone}` : '自动调度未启用';
  $('category').innerHTML = '<option value="">全部方向</option>' + topics.map(([name, n]) => `<option value="${esc(name)}">${esc(name)} · ${n}</option>`).join('');
  if (category && !topics.some(([name]) => name === category)) $('category').insertAdjacentHTML('beforeend', `<option value="${esc(category)}">${esc(category)} · 0</option>`);
  $('category').value = category;
  const year = routeFilters?.year ?? $('year').value;
  const years = [...new Set(papers.map(p => p.card.year).filter(Boolean))].sort((a,b) => b-a);
  $('year').innerHTML = '<option value="">全部年份</option>' + years.map(y => `<option value="${y}">${y} 年</option>`).join('') + (papers.some(p => !p.card.year) ? '<option value="unknown">年份待核对</option>' : '');
  if (year && !years.some(y => String(y) === year) && !(year === 'unknown' && papers.some(p => !p.card.year))) $('year').insertAdjacentHTML('beforeend', `<option value="${esc(year)}">${esc(year === 'unknown' ? '年份待核对' : year + ' 年')} · 0</option>`);
  $('year').value = year;
  if (routeFilters) {
    $('search').value = routeFilters.query;
    $('favorites-only').checked = routeFilters.favorites;
    $('sort').value = routeFilters.sort;
  }
  $('discovery-view').hidden = pageView !== 'discover';
  $('library-view').hidden = pageView !== 'catalog';
  $('management').hidden = pageView !== 'workspace';
  const activeNav = pageView === 'workspace' ? 'workspace' : pageView === 'discover' ? 'discover' : $('favorites-only').checked ? 'favorites' : 'catalog';
  ['discover', 'catalog', 'favorites', 'workspace'].forEach(name => {
    if (name === activeNav) $('nav-' + name).setAttribute('aria-current', 'page');
    else $('nav-' + name).removeAttribute('aria-current');
  });
  $('catalog-categories').innerHTML = [['', papers.length], ...topics].map(([name, count]) =>
    `<a href="${esc(catalogHash({...currentFilters(), category: name, page: 1}))}"${category === name ? ' aria-current="page"' : ''}><span>${esc(name || '全部分类')}</span><span>${count}</span></a>`).join('');
  $('tag-cloud').innerHTML = tags.slice(0, 10).map(([name]) => `<button class="chip ${tag === name ? 'active' : ''}" data-tag="${esc(name)}">${esc(name)}</button>`).join('');
  $('inbox-path').textContent = $('guide-path').textContent = state.inbox;
  $('run').disabled = !state.agent.configured || state.running;
  $('run').textContent = state.running ? '正在整理…' : state.agent.configured ? '开始整理' : '请先配置整理方式';
  renderDiscovery(); renderPapers(); renderInbox(); renderJobs();
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
  $('category-breadcrumb').textContent = category || '全部论文';
  $('catalog-description').textContent = category ? categoryDescription(category) : '按研究方向、作者与关键词，找到值得继续阅读的论文。';
  $('clear-filters').hidden = !tag && !year && !query && !$('favorites-only').checked;
  const summary = [$('favorites-only').checked && '仅看收藏', category, tag, year && (year === 'unknown' ? '年份待核对' : year + ' 年')].filter(Boolean);
  $('filter-summary').hidden = !summary.length;
  $('filter-summary').textContent = `当前筛选：${summary.join(' / ')} · ${papers.length} 篇论文`;
  pageCount = Math.max(1, Math.ceil(papers.length / PAGE_SIZE));
  const page = Math.min(Math.max(1, currentPage), pageCount);
  if (page !== currentPage) {
    currentPage = page;
    if (pageView === 'catalog') window.history.replaceState(null, '', catalogHash(currentFilters()));
  }
  const offset = (currentPage - 1) * PAGE_SIZE;
  $('papers-prev').disabled = currentPage <= 1;
  $('papers-next').disabled = currentPage >= pageCount;
  $('page-label').textContent = `第 ${currentPage} / ${pageCount} 页`;
  $('page-summary').textContent = papers.length ? `显示 ${offset + 1}–${Math.min(offset + PAGE_SIZE, papers.length)} 条，共 ${papers.length} 条文献` : '共 0 条文献';
  $('papers-pagination').hidden = !papers.length;
  $('papers').innerHTML = papers.slice(offset, offset + PAGE_SIZE).map(p => paperCard(p)).join('') || `<div class="empty"><div class="empty-symbol">⌕</div><h3>${ready().length ? '没有找到匹配的论文' : '你的研究书架，等待第一篇论文'}</h3><p>${ready().length ? '试试其他关键词，或清除方向、标签与年份筛选。' : '点击“添加论文”，将 PDF 放入待整理区并完成整理。'}</p></div>`;
}
// A stable visual cue for a topic; category names and links remain authoritative.
function topicVisual(name) {
  const known = {'语言模型': ['lilac', 'language'], '数据选择': ['blue', 'layers'],
    '表征学习': ['teal', 'network'], '泛化理论': ['amber', 'chart'], '核方法': ['rose', 'grid']};
  const [tone, icon] = Object.hasOwn(known, name) ? known[name] : ['lilac', 'folder'];
  return {tone: 'tone-' + tone, icon: 'icon-' + icon};
}
function paperCard(p, recommended = false) {
    const c = p.card, visual = topicVisual(c.category);
    return `<article class="paper-card ${visual.tone} ${recommended ? 'recommended-card' : ''}">${recommended ? '<span class="sr-only">随机推荐</span>' : ''}<div class="card-top"><span class="category-label">${esc(c.category)}</span><span class="card-year">${c.year || '年份待核对'}</span><button class="favorite ${p.favorite ? 'on' : ''}" data-favorite="${p.id}" aria-label="${p.favorite ? '取消收藏' : '收藏'}：${esc(c.title)}" aria-pressed="${p.favorite}"><svg class="icon" aria-hidden="true"><use href="#icon-star"/></svg></button></div><button class="card-title" data-open="${p.id}">${esc(c.title)}</button><div class="authors" title="${esc(c.authors.join(' · '))}">${esc(c.authors.join(' · ') || '作者待核对')}</div><p class="summary">${esc(c.reading?.takeaway || c.summary)}</p><div class="card-tags">${c.tags.slice(0, 3).map(t => `<button class="chip" data-tag="${esc(t)}">${esc(t)}</button>`).join('')}${c.tags.length > 3 ? `<span class="chip">+${c.tags.length - 3}</span>` : ''}</div><div class="card-publication"><span class="journal" title="${esc(c.venue || '出版信息待核对')}">${esc(c.venue || '出版信息待核对')}</span><span>${p.bibliography_only ? '导入题录' : hasReading(c) ? '详细解读' : '基础卡片'}</span></div><div class="card-bottom"><span class="${p.bibliography_only || p.status === 'review' || !p.available ? 'status-review' : 'status-ready'}">${!p.available ? '◌ 原件缺失' : p.bibliography_only ? '◌ 题录已导入 · 待原文核验' : p.status === 'review' ? '◌ 信息待核对' : '◦ 已整理'}</span><button data-open="${p.id}">阅读论文详情 <span>↗</span></button></div></article>`;

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
    if (b.dataset.tag) navigateCatalog({... (pageView === 'catalog' ? currentFilters() : {}), tag: tag === b.dataset.tag ? '' : b.dataset.tag, page: 1});
    if (b.dataset.detailTag) navigateCatalog({tag: b.dataset.detailTag});
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
$('search').addEventListener('input', () => {clearTimeout(searchTimer); searchTimer = setTimeout(() => navigateCatalog({...currentFilters(), page: 1}, true, false), 120);});
$('year').onchange = $('sort').onchange = $('favorites-only').onchange = () => navigateCatalog({...currentFilters(), page: 1}, false, false);
$('category').onchange = () => navigateCatalog({...currentFilters(), category: $('category').value, page: 1}, false, false);
$('clear-filters').onclick = () => navigateCatalog({category}, false, false);
$('discovery-search-form').onsubmit = event => { event.preventDefault(); navigateCatalog({query: $('discovery-search').value.trim()}); };
$('shuffle-recommendations').onclick = () => { recommendedPapers(true); renderDiscovery(); };
$('papers-prev').onclick = () => { if (currentPage > 1) navigateCatalog({...currentFilters(), page: currentPage - 1}); };
$('papers-next').onclick = () => { if (currentPage < pageCount) navigateCatalog({...currentFilters(), page: currentPage + 1}); };
window.addEventListener('hashchange', () => applyRoute(true));
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
document.addEventListener('keydown', e => {if (e.key === '/' && pageView !== 'workspace' && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName) && !document.activeElement.isContentEditable && !$('detail').open && !$('guide').open && !$('login').open && !$('provider-settings').open) {e.preventDefault(); $(pageView === 'discover' ? 'discovery-search' : 'search').focus();}});
setInterval(() => {if (!$('login').open && !$('detail').open && !document.hidden) refresh(true);}, 30000);
refresh(true);

function describeProvider() {
  const mode = $('provider-mode').value;
  $('provider-description').textContent = mode === 'auto' ? '先尝试 Agent；未接入、超时、调用失败或卡片校验失败时，自动改用已配置的 API。每篇论文只归档一次。' : mode === 'agent' ? '只调用服务器上的 Agent，失败后保留论文等待重试。' : '直接调用自定义 API，使用同一份 skill 生成并校验卡片。';
}
async function loadProviderSettings() {
  const request = ++providerRequest;
  providerLoaded = false;
  providerBusy = true;
  $('provider-fields').disabled = true;
  $('save-provider').disabled = true;
  $('retry-settings').hidden = true;
  $('settings-status').textContent = '正在加载整理设置…';
  try {
    // A reopened dialog must wait for an earlier save before reading its result.
    if (providerSavePromise) await providerSavePromise.catch(() => {});
    if (request !== providerRequest || !$('provider-settings').open) return;
    const c = await api('/api/settings');
    if (request !== providerRequest || !$('provider-settings').open) return;
    fillProviderSettings(c);
    providerLoaded = true;
    $('settings-status').textContent = '';
  } catch (error) {
    if (request !== providerRequest || !$('provider-settings').open) return;
    $('settings-status').textContent = `设置加载失败：${error.message}`;
    $('retry-settings').hidden = false;
  } finally {
    if (request === providerRequest && $('provider-settings').open) {
      providerBusy = false;
      $('provider-fields').disabled = !providerLoaded;
      $('save-provider').disabled = !providerLoaded;
    }
  }
}
function fillProviderSettings(c) {
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
  describeProvider();
}
function openProviderSettings() {
  if ($('provider-settings').open) return;
  $('provider-settings').showModal();
  return loadProviderSettings();
}
$('provider-settings').addEventListener('close', () => {
  ++providerRequest;
  providerLoaded = false;
  providerBusy = false;
  $('api-key').value = '';
  $('clear-api-key').checked = false;
  $('provider-fields').disabled = true;
  $('save-provider').disabled = true;
});
$('settings-button').onclick = $('workspace-settings').onclick = openProviderSettings;
$('close-settings').onclick = () => $('provider-settings').close();
$('retry-settings').onclick = () => { if ($('provider-settings').open && !providerBusy) return loadProviderSettings(); };
$('provider-mode').onchange = describeProvider;
$('provider-form').onsubmit = async event => {
  event.preventDefault();
  if (!providerLoaded || providerBusy || !$('provider-settings').open) return;
  const payload = {
    mode: $('provider-mode').value, api_base_url: $('api-base-url').value.trim(),
    api_model: $('api-model').value.trim(), api_key: $('api-key').value,
    clear_api_key: $('clear-api-key').checked, api_json_mode: $('api-json-mode').checked,
    api_timeout: Number($('api-timeout').value), agent_timeout: Number($('agent-timeout').value)
  };
  if (payload.mode === 'api' && (!payload.api_base_url || !payload.api_model)) {
    $('settings-status').textContent = '请填写 API Base URL 和模型名称'; return;
  }
  const request = ++providerRequest;
  providerBusy = true;
  $('provider-fields').disabled = true;
  $('save-provider').disabled = true;
  $('settings-status').textContent = '正在保存整理设置…';
  const saving = api('/api/settings', {method: 'PATCH', body: JSON.stringify(payload)});
  providerSavePromise = saving;
  try {
    const c = await saving;
    if (request === providerRequest && $('provider-settings').open) {
      fillProviderSettings(c);
      $('settings-status').textContent = c.configured ? '已保存，对下一批整理生效' : '已保存，请继续配置可用的整理通道';
    }
    await refresh(true);
  } catch (error) {
    if (request === providerRequest && $('provider-settings').open) $('settings-status').textContent = error.message;
  } finally {
    if (providerSavePromise === saving) providerSavePromise = null;
    if (request === providerRequest && $('provider-settings').open) {
      providerBusy = false;
      $('provider-fields').disabled = false;
      $('save-provider').disabled = false;
    }
  }
};
