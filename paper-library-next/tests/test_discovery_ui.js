"use strict";
// Exercise the actual browser event handlers with an in-memory API and DOM.
// No server, browser, model provider, or filesystem data store is started.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/app.js', 'utf8');
let checks = 0;
function check(value, message) { assert.ok(value, message); checks++; }
function equal(actual, expected, message) { assert.deepEqual(actual, expected, message); checks++; }
const clone = value => JSON.parse(JSON.stringify(value));
const identifier = number => number.toString(16).padStart(64, '0');
function paper(number, category = '语音识别 & 合成') {
  return {id: identifier(number), filename: `paper-${number}.pdf`, status: 'ready',
    available: true, fulltext_available: true, notes: '', favorite: false, updated: '2026-10-29',
    card: {title: `Research ${number}`, category, authors: ['Author'], year: 2024,
      venue: 'Conference', tags: ['语音', 'shared'], summary: 'A research summary.',
      contributions: ['A contribution.'], limitations: [], evidence: [], reading: {},
      needs_review: false, updated_at: '2026-10-29'}};
}
function bibliography(number, category) {
  const result = paper(number, category);
  result.bibliography = {...result.card, fulltext_policy: 'restricted', provenance: [
    {label: 'Existing index', sha256: 'b'.repeat(64), record_id: 'indexed-1'}]};
  result.card = null;
  result.status = 'bibliography';
  result.fulltext_available = true;
  return result;
}
const stateFor = papers => ({papers, jobs: [], agent: {configured: false, enabled: false},
  running: false, inbox: '/fixture/inbox'});
const idsIn = html => [...new Set([...html.matchAll(/data-open="([a-f0-9]{64})"/g)].map(match => match[1]))];
const flush = () => new Promise(resolve => setImmediate(resolve));

async function setup(pathname, papers, hash = '', options = {}) {
  let serverState = stateFor(clone(papers));
  const nodes = new Map(), documentHandlers = new Map(), windowHandlers = new Map();
  const requests = [], timers = new Map(), visits = [], created = [];
  let timer = 0, seed = 391;
  const document = {hidden: false, activeElement: {tagName: 'BODY'}};
  const node = id => {
    if (!nodes.has(id)) {
      const events = new Map(), classes = new Set();
      let html = '', text = '';
      const element = {id, value: id === 'sort' ? 'newest' : '', checked: false, hidden: false,
        open: false, disabled: false, scrollTop: 0, dataset: {}, tagName: 'DIV', children: [],
        get innerHTML() { return html; }, set innerHTML(value) { html = String(value); },
        get textContent() { return text; }, set textContent(value) { text = String(value); },
        insertAdjacentHTML(position, value) { html += value; },
        setAttribute(name, value) { this[name] = String(value); },
        removeAttribute(name) { delete this[name]; },
        classList: {add(name) { classes.add(name); }, remove(name) { classes.delete(name); },
          toggle(name, value) { if (value) classes.add(name); else classes.delete(name); }},
        addEventListener(name, handler) { events.set(name, handler); },
        async dispatch(name, event = {}) { if (events.has(name)) await events.get(name)(event); },
        showModal() { this.open = true; },
        close() { this.open = false; if (events.has('close')) events.get('close')(); },
        focus() { document.activeElement = this; }, scrollIntoView() {}, appendChild(child) {child.parentNode=this;this.children.push(child)},
        append(...children) { children.forEach(child=>this.appendChild(child)); },
        prepend(child) {child.parentNode=this;this.children.unshift(child)},
        querySelector(tag) { const visit=n=>n.tagName===tag.toUpperCase()?n:n.children.map(visit).find(Boolean);return this.children.map(visit).find(Boolean); }};
      nodes.set(id, element);
    }
    return nodes.get(id);
  };
  document.getElementById = node;
  document.createElement = tag => { const element=node('generated-'+created.length); element.tagName=tag.toUpperCase();created.push(element);return element; };
  document.querySelector = selector => selector === '.agent-state' ? node('agent-state') :
    selector === 'dialog[open]' ? ['detail', 'guide', 'login', 'provider-settings'].map(node).find(item => item.open) || null : null;
  document.querySelectorAll = () => [];
  document.addEventListener = (name, handler) => documentHandlers.set(name, handler);
  document.body = node('body');
  const location = {pathname, hash};
  const storage = options.storage || new Map();
  const window = {location, localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)}, addEventListener: (name, handler) => windowHandlers.set(name, handler),
    history: {pushState(data, title, url) { visits.push(url); location.hash = url; },
      replaceState(data, title, url) { location.hash = url; }}};
  const math = Object.create(Math);
  math.random = () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; };
  const fetch = async (url, options = {}) => {
    requests.push({url, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null});
    const apiPath = url.replace(/^\/papers(?=\/api\/)/, '');
    if (apiPath === '/api/settings' && settingsRequest) return settingsRequest(options);
    if (['/api/state', '/api/catalog'].includes(apiPath) && !options.method) {
      if (stateResponse) { const response=stateResponse(apiPath); if(response) return response; }
      return {ok: true, status: 200, json: async () => clone(serverState)};
    }
    const match = apiPath.match(/^\/api\/papers\/([a-f0-9]{64})$/);
    if (match && options.method === 'PATCH') {
      const current = serverState.papers.find(item => item.id === match[1]);
      Object.assign(current, JSON.parse(options.body));
      return {ok: true, status: 200, json: async () => clone(current)};
    }
    throw new Error(`Unexpected API request: ${options.method || 'GET'} ${url}`);
  };
  const settingsRequest = options.settingsRequest, stateResponse = options.stateResponse;
  const context = {document, window, URL, URLSearchParams, console, fetch, Math: math,
    navigator: {clipboard: {writeText: async () => {}}},
    setTimeout(callback) { timers.set(++timer, callback); return timer; },
    clearTimeout(id) { timers.delete(id); }, setInterval() { return ++timer; }, clearInterval() {}};
  vm.createContext(context);
  vm.runInContext(source, context);
  await flush();
  async function click(id, dataset = {}) {
    const button = {...node(id), id, dataset};
    await documentHandlers.get('click')({target: {closest: () => button}});
    if (node(id).onclick) await node(id).onclick();
    await flush();
  }
  async function route(value) {
    location.hash = value;
    await windowHandlers.get('hashchange')();
    await flush();
  }
  return {node, requests, visits, location, click, route, storage, created,
    async refresh() { await node('refresh').onclick(); await flush(); },
    async submitSearch(value) { node('discovery-search').value = value;
      node('discovery-search-form').onsubmit({preventDefault() {}}); await flush(); },
    async inputSearch(value) { node('search').value = value; await node('search').dispatch('input');
      for (const [id, callback] of [...timers]) { timers.delete(id); callback(); } await flush(); },
    async submitSettings() { await node('provider-form').onsubmit({preventDefault() {}}); await flush(); },
    async keydown(key) { let prevented = false; await documentHandlers.get('keydown')({key, preventDefault() { prevented = true; }}); return prevented; },
    async escapeSettings() { let prevented = false; await node('provider-settings').dispatch('cancel', {preventDefault() { prevented = true; }}); if (!prevented) node('provider-settings').close(); await flush(); },
    setPapers(value) { serverState = stateFor(clone(value)); }};
}

async function fullCollection(pathname) {
  const unusual = '临床言语 / 中文?', unsafe = '\"><script>alert(1)</script>';
  const collection = [paper(1), paper(2), bibliography(3, unusual), paper(4, '__proto__'),
    paper(5, unsafe), paper(6, '语言模型'), paper(7, '语言模型')];
  const waiting = {...paper(8), card: null, status: 'pending'};
  const app = await setup(pathname, [...collection, waiting]);
  const {node} = app;
  check(!node('discovery-view').hidden && node('library-view').hidden, 'Entry opens discovery, not every paper');
  equal(node('category-count').textContent, '5', 'Categories come from cards and arbitrary imported bibliography');
  check(node('category-grid').innerHTML.includes(unusual), 'Imported category is retained');
  check(node('category-grid').innerHTML.includes('__proto__'), 'Prototype-like category remains an ordinary category');
  check(node('category-grid').innerHTML.includes('&lt;script&gt;') && !node('category-grid').innerHTML.includes('<script>'), 'Category HTML is escaped');
  check(!node('category-grid').innerHTML.includes('8 篇'), 'Unprocessed input is excluded');
  let recommendations = idsIn(node('recommended-papers').innerHTML);
  equal(recommendations.length, 3, 'Three distinct recommendations');
  check(recommendations.every(id => collection.some(item => item.id === id)), 'Only ready cards and bibliography are recommended');
  check(node('recommended-papers').innerHTML.includes('随机推荐'), 'Recommendation basis is explicit');
  await app.refresh();
  equal(idsIn(node('recommended-papers').innerHTML), recommendations, 'Refreshing does not reshuffle');
  await app.click('favorite-fixture', {favorite: recommendations[0]});
  equal(idsIn(node('recommended-papers').innerHTML), recommendations, 'Saving a favorite does not reshuffle');
  check(node('recommended-papers').innerHTML.includes('aria-pressed="true"'), 'Recommendation updates saved favorite state');
  for (let attempt = 0; attempt < 12; attempt++) {
    await app.click('shuffle-recommendations');
    const changed = idsIn(node('recommended-papers').innerHTML);
    equal(changed.length, 3, 'A new batch has no duplicates');
    check(changed.some(id => !recommendations.includes(id)), 'A new batch includes an unseen item when possible');
    recommendations = changed;
  }
  const categoryLink = node('category-grid').innerHTML.match(/href="([^\"]+)" aria-label="临床言语/)[1].replace(/&amp;/g, '&');
  check(categoryLink.includes('%'), 'Category links use encoded URL values');
  await app.route(categoryLink);
  check(node('discovery-view').hidden && !node('library-view').hidden, 'Category link opens the card list');
  equal(node('category').value, unusual, 'Encoded arbitrary category round-trips');
  equal(idsIn(node('papers').innerHTML), [identifier(3)], 'Category contains exactly its papers');
  check(node('papers').innerHTML.includes('阅读原文') && !node('papers').innerHTML.includes('待原文核验'), 'Bibliography has a direct PDF action without repeated workflow labels');
  await app.inputSearch('no matching title');
  check(node('papers').innerHTML.includes('没有找到匹配的论文'), 'Search filters within the category');
  await app.click('clear-filters');
  equal(node('category').value, unusual, 'Clear filters retains the category page');
  equal(idsIn(node('papers').innerHTML), [identifier(3)], 'Clear filters restores category papers');
  await app.click('open-fixture', {open: identifier(3)});
  check(node('detail').open, 'Cards open the original reader');
  check(node('detail-content').innerHTML.includes('Existing index'), 'Bibliography provenance remains visible');
  check(!node('detail-content').innerHTML.includes('下载原件'), 'Restricted bibliography does not expose a download');
  check(node('generate-reading').hidden, 'Bibliography does not acquire automatic reading actions');
  node('notes').value = 'Unsaved research note';
  await node('detail').dispatch('input', {target: {id: 'notes'}});
  await app.click('detail-tag-fixture', {detailTag: '语音'});
  check(!node('detail').open && !node('library-view').hidden, 'Reader tag opens results and closes the reader');
  equal(node('category').value, '', 'Reader tag searches across categories');
  check(app.location.hash.includes('tag='), 'Reader tag is linkable');
  await app.click('open-fixture', {open: identifier(3)});
  check(node('detail-content').innerHTML.includes('Unsaved research note'), 'Route changes retain unsaved note drafts');
  await app.route('#discover');
  await app.submitSearch('Research 6');
  equal(idsIn(node('papers').innerHTML), [identifier(6)], 'Homepage search searches the full collection');
  await app.route('#discover');
  check(!node('discovery-view').hidden && node('library-view').hidden, 'Returning via hash restores discovery');
  await app.route('#catalog?category=missing');
  check(node('papers').innerHTML.includes('没有找到匹配的论文'), 'Missing category yields a clear empty state');
  check(app.requests.every(call => call.url.startsWith(pathname.startsWith('/papers/') ? '/papers/api/' : '/api/')), 'API base remains correct for both deployments');
  check(app.requests.every(call => call.method === 'GET' || call.method === 'PATCH'), 'Browsing and randomizing never launches curation');
}

async function initialLinksAndSmallCollections(pathname) {
  const category = '语言模型 / NLP & 中文';
  const hash = '#catalog?' + new URLSearchParams({category, year: '2024'});
  const deep = await setup(pathname, [paper(1, category), paper(2, 'other')], hash);
  check(deep.node('discovery-view').hidden && !deep.node('library-view').hidden, 'Initial deep link opens collection after the first API response');
  equal(deep.node('category').value, category, 'Initial link preserves Chinese category');
  equal(idsIn(deep.node('papers').innerHTML), [identifier(1)], 'Initial deep link applies category filters');
  for (const size of [0, 1, 3]) {
    const app = await setup(pathname, Array.from({length: size}, (_, index) => paper(index + 1)));
    equal(idsIn(app.node('recommended-papers').innerHTML).length, size, `Small library of ${size} is not duplicated`);
    check(app.node('shuffle-recommendations').disabled, `Small library of ${size} disables unhelpful reshuffle`);
    if (!size) {
      check(app.node('recommended-papers').innerHTML.includes('等待第一篇推荐论文'), 'Empty recommendations have an explanatory state');
      check(app.node('category-grid').innerHTML.includes('分类将随论文一起出现'), 'Empty categories have an explanatory state');
    }
  }
}

async function largeCollectionAndWorkspace(pathname) {
  const collection = Array.from({length: 336}, (_, index) => bibliography(index + 1, `研究方向 ${index % 26}`));
  collection[0].favorite = true;
  const app = await setup(pathname, collection, '#catalog');
  const {node} = app;
  equal(node('nav-all-count').textContent, '336', 'Navigation includes all imported bibliography');
  equal(node('nav-favorite-count').textContent, '1', 'Navigation counts favorites');
  check(node('stat-categories').innerHTML.startsWith('26<'), 'Statistics count 26 categories');
  equal((node('catalog-categories').innerHTML.match(/<a /g) || []).length, 27, 'Sidebar includes every category and the all-category entry');
  equal(node('nav-catalog')['aria-current'], 'page', 'Catalog navigation is active');
  equal(idsIn(node('papers').innerHTML).length, 12, 'Catalog is limited to 12 cards per page');
  check(node('papers-prev').disabled && !node('papers-next').disabled, 'First-page navigation is bounded');
  const seen = [...idsIn(node('papers').innerHTML)];
  for (let page = 2; page <= 28; page++) {
    await app.click('papers-next');
    seen.push(...idsIn(node('papers').innerHTML));
  }
  equal(new Set(seen).size, 336, 'Paging visits every record exactly once');
  equal(seen.length, 336, 'Paging never duplicates records');
  check(app.location.hash.includes('page=28'), 'Current page is linkable');
  equal(node('page-label').textContent, '第 28 / 28 页', 'Last-page label is accurate');
  equal(node('page-summary').textContent, '显示 325–336 条，共 336 条文献', 'Range is accurate at collection end');
  check(node('papers-next').disabled, 'Next page is disabled at the end');
  await app.route('#catalog?page=999');
  check(app.location.hash.includes('page=28'), 'Oversized deep-link page is clamped in the URL');
  await app.inputSearch('Research 336');
  equal(idsIn(node('papers').innerHTML), [identifier(336)], 'Search resets pagination before filtering');
  check(!app.location.hash.includes('page='), 'First page is canonical without a page parameter');
  await app.route('#catalog?' + new URLSearchParams({category: '研究方向 0', page: '2'}));
  equal(idsIn(node('papers').innerHTML).length, 1, 'Category pagination has a partial final page');
  check(node('catalog-categories').innerHTML.includes('aria-current="page"><span>研究方向 0'), 'Sidebar highlights the selected category');
  node('year').value = '2024';
  await node('year').onchange();
  equal(idsIn(node('papers').innerHTML).length, 12, 'Changing a filter resets the category page');
  await app.route('#catalog?page=28');
  app.setPapers(collection.slice(0, 13));
  await app.refresh();
  equal(node('page-label').textContent, '第 2 / 2 页', 'Refresh clamps a page after collection shrinkage');
  equal(idsIn(node('papers').innerHTML), [identifier(13)], 'Clamping preserves the remaining last-page result');
  await app.route('#favorites');
  equal(idsIn(node('papers').innerHTML), [identifier(1)], 'Legacy favorites route still works');
  equal(node('nav-favorites')['aria-current'], 'page', 'Favorites navigation is active');
  check(!node('nav-catalog')['aria-current'], 'Only one navigation item is active');
  await app.route('#workspace');
  check(!node('management').hidden && node('discovery-view').hidden && node('library-view').hidden, 'Workspace is an independent route');
  equal(node('nav-workspace')['aria-current'], 'page', 'Workspace navigation is active');
  check(!(await app.keydown('/')), 'Workspace does not focus a hidden search field');
  await app.route('#discover');
  check(node('management').hidden && !node('discovery-view').hidden, 'Leaving workspace restores discovery');
  check(app.requests.every(call => call.method === 'GET'), 'Scale, paging, routes and filters do not start jobs');
}

const settingsFixture = () => ({mode: 'auto', api_base_url: 'https://model.example/v1', api_model: 'example-model',
  api_key_set: true, api_timeout: 120, agent_timeout: 300, api_json_mode: true, agent_configured: false, configured: true});
const response = (data, status = 200) => ({ok: status < 400, status, json: async () => clone(data)});
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return {promise, resolve}; };

async function providerDialog(pathname) {
  let fail = true, configuration = settingsFixture();
  const app = await setup(pathname, [paper(1)], '', {settingsRequest: async options => {
    if (fail) return response({error: 'Fixture unavailable'}, 503);
    if (options.method === 'PATCH') {
      const payload = JSON.parse(options.body);
      configuration = {...configuration, ...payload, api_key_set: payload.clear_api_key ? false : !!payload.api_key || configuration.api_key_set};
      delete configuration.api_key;
    }
    return response(configuration);
  }});
  const {node} = app;
  check(!app.requests.some(call => call.url.endsWith('/settings')), 'Settings are fetched only when opened');
  await app.click('settings-button');
  check(node('provider-settings').open, 'Header settings button opens a native dialog');
  check(node('provider-fields').disabled && node('save-provider').disabled && !node('retry-settings').hidden, 'Load failure prevents saving and exposes retry');
  await app.submitSettings();
  check(!app.requests.some(call => call.method === 'PATCH'), 'A failed load cannot overwrite server settings');
  fail = false;
  await app.click('retry-settings');
  check(!node('provider-fields').disabled && !node('save-provider').disabled && node('retry-settings').hidden, 'Retry restores the editable form');
  equal(node('api-key').value, '', 'Saved API key is never returned to its input');
  node('api-model').value = 'unsaved-model';
  node('api-key').value = 'draft-secret';
  await app.refresh();
  equal(node('api-model').value, 'unsaved-model', 'Background refresh preserves configuration drafts');
  equal(node('api-key').value, 'draft-secret', 'Background refresh preserves the current key draft');
  check(!(await app.keydown('/')), 'Search shortcut is inactive while settings are open');
  await app.click('close-settings');
  check(!node('provider-settings').open, 'Close button closes settings');
  equal(node('api-key').value, '', 'Closing clears the key draft');
  await app.click('workspace-settings');
  equal(node('api-model').value, 'example-model', 'Reopening reloads saved settings');
  node('provider-mode').value = 'api';
  node('api-model').value = 'new-model';
  node('api-base-url').value = '';
  await app.submitSettings();
  check(!app.requests.some(call => call.method === 'PATCH'), 'Incomplete API configuration is rejected before saving');
  node('api-base-url').value = configuration.api_base_url;
  fail = true;
  node('api-key').value = 'retry-draft';
  await app.submitSettings();
  check(!node('save-provider').disabled && !node('provider-fields').disabled, 'Save errors leave the form available for retry');
  equal(node('api-key').value, 'retry-draft', 'Save errors retain the draft for retry');
  fail = false;
  node('api-key').value = '';
  await app.submitSettings();
  const save = app.requests.filter(call => call.method === 'PATCH').at(-1);
  check(save && save.url.endsWith('/api/settings'), 'Settings use only the settings PATCH endpoint');
  equal(save.body.api_key, '', 'Blank key requests retention of the saved key');
  equal(save.body.clear_api_key, false, 'Key retention is the default');
  check(node('settings-status').textContent.includes('已保存'), 'Successful save is confirmed');
  node('clear-api-key').checked = true;
  await app.submitSettings();
  check(app.requests.filter(call => call.method === 'PATCH').at(-1).body.clear_api_key, 'Explicit key removal is passed through');
  check(!configuration.api_key_set, 'Explicit key removal updates displayed state');
  node('api-key').value = 'another-draft';
  await app.escapeSettings();
  check(!node('provider-settings').open && !node('api-key').value, 'Native Escape close clears the key');
  check(app.requests.every(call => call.method === 'GET' || (call.method === 'PATCH' && call.url.endsWith('/settings'))), 'Settings do not scan, run or generate a reading');
}

async function providerRaces(pathname) {
  const first = deferred(), second = deferred();
  let loads = 0;
  const app = await setup(pathname, [paper(1)], '', {settingsRequest: () => (++loads === 1 ? first.promise : second.promise)});
  const firstOpen = app.click('settings-button');
  await flush();
  await app.click('close-settings');
  const secondOpen = app.click('settings-button');
  await flush();
  second.resolve(response({...settingsFixture(), api_model: 'current-model'}));
  await secondOpen;
  app.node('api-model').value = 'current-draft';
  first.resolve(response({...settingsFixture(), api_model: 'obsolete-model'}));
  await firstOpen;
  equal(app.node('api-model').value, 'current-draft', 'Late response from a previous opening cannot replace the current draft');
  check(!app.node('provider-fields').disabled, 'Stale response cannot disable the current form');

  const saving = deferred();
  let configuration = settingsFixture();
  const savingApp = await setup(pathname, [paper(1)], '', {settingsRequest: async options => {
    if (options.method === 'PATCH') {
      await saving.promise;
      configuration.api_model = JSON.parse(options.body).api_model;
    }
    return response(configuration);
  }});
  await savingApp.click('settings-button');
  savingApp.node('api-model').value = 'saved-after-reopen';
  const submit = savingApp.submitSettings();
  await flush();
  await savingApp.click('close-settings');
  const reopen = savingApp.click('settings-button');
  await flush();
  equal(savingApp.requests.filter(call => call.url.endsWith('/settings') && call.method === 'GET').length, 1, 'Reopening waits for the in-flight save before fetching');
  check(savingApp.node('provider-fields').disabled, 'Reopened settings remain disabled while the prior save finishes');
  saving.resolve();
  await Promise.all([submit, reopen]);
  equal(savingApp.node('api-model').value, 'saved-after-reopen', 'Reopened settings show the result of the completed save');
  check(!savingApp.node('save-provider').disabled && !savingApp.node('provider-fields').disabled, 'An older save cannot disable the reopened form');
}

function insightFixture() {
  return {schema_version:1, source_digest:identifier(1),
    abstract:{status:'available',language:'en',pages:[1,2],text:'Full original abstract begins.\n\n'+ 'Complete source sentence. '.repeat(90) + 'Final abstract sentence <not markup>.'},
    keywords:['抑郁语音','对比学习','跨语言'],keywords_source:'curated',
    summary:{overview:'通过跨语言对齐提取可迁移的抑郁语音表示。',problem:'不同语言的数据分布存在差异。',method:'结合预训练语音特征与监督式对比学习。',findings:'报告跨语言实验及泄漏控制对照。',limitations:''},
    evidence:[{field:'summary.method',page:2,quote:'We use <contrastive> alignment.'}],
    coverage:'abstract',generated_by:'codex',updated_at:'2026-11-21T00:00:00Z'};
}
async function insightReading(pathname) {
  const enriched = {...bibliography(1,'跨域研究'),insight:insightFixture()};
  const original = clone(enriched);
  const app = await setup(pathname, [enriched,paper(2,'其他')], '#catalog');
  const {node} = app;
  check(node('papers').innerHTML.includes(enriched.insight.summary.overview), 'Cards prefer the Chinese overview');
  check(!node('papers').innerHTML.includes('Full original abstract begins'), 'The complete original abstract does not fill catalog cards');
  check(node('papers').innerHTML.includes('data-tag="跨语言"'), 'Curated keywords appear on catalog cards');
  await app.click('open-fixture',{open:identifier(1)});
  let html=node('detail-content').innerHTML;
  const keywordIndex=html.indexOf('id="reader-keywords"'), summaryIndex=html.indexOf('id="reader-chinese-summary"'), abstractIndex=html.indexOf('id="reader-abstract"');
  check(keywordIndex>=0 && keywordIndex<summaryIndex && summaryIndex<abstractIndex, 'Reader starts with keywords, Chinese guide, then original abstract');
  check(html.includes('根据论文内容归纳的主题词'), 'Keywords are explicitly curated topics, not claimed as author keywords');
  check(html.includes('基于原文摘要整理'), 'Coverage does not imply full-paper reading');
  for (const label of ['研究问题','研究方法','主要结果']) check(html.includes(`<h4>${label}</h4>`), `${label} is presented as a readable subsection`);
  check(!html.includes('<h4>局限与适用范围</h4>'), 'Empty summary fields do not create empty headings');
  check(html.includes('Final abstract sentence &lt;not markup&gt;.'), 'Complete abstract tail is retained and escaped');
  check(html.includes('lang="en"') && html.includes('英文摘要'), 'The original abstract retains its language');
  check(html.includes('/pdf#page=1') && html.includes('/pdf#page=2'), 'Abstract and evidence page references lead to the original PDF');
  check(html.includes('We use &lt;contrastive&gt; alignment.'), 'Source evidence is escaped and available to inspect');
  check(html.includes('data-section="reader-abstract"') && html.includes('data-section="reader-chinese-summary"'), 'Reading navigation reaches the new sections');
  check(html.includes('查看原有索引简介'), 'Legacy index prose remains distinct from the original abstract');
  check(!html.includes('<h3>摘要</h3>'), 'A single index sentence is not labeled as a full abstract');
  check(node('generate-reading').hidden, 'Viewing enriched imported records does not enable automatic curation');
  await app.click('keyword-fixture',{detailTag:'跨语言'});
  equal(idsIn(node('papers').innerHTML),[identifier(1)],'Clicking a curated keyword finds its paper');
  await app.route('#catalog');
  await app.inputSearch('对比学习');
  equal(idsIn(node('papers').innerHTML),[identifier(1)],'New Chinese content is searchable');
  await app.inputSearch('Final abstract sentence');
  equal(idsIn(node('papers').innerHTML),[identifier(1)],'Original abstract text is searchable');
  const missing={...enriched,insight:{...insightFixture(),abstract:{status:'missing',reason:'原文件未提供独立摘要。'},summary:{overview:'',problem:'',method:'',findings:'',limitations:''},coverage:'selected_pages'}};
  app.setPapers([missing]); await app.refresh();
  await app.click('open-fixture',{open:identifier(1)});
  html=node('detail-content').innerHTML;
  check(html.includes('原文件未提供独立摘要。') && !html.includes('Full original abstract'), 'Missing abstract displays its reason without fabricating content');
  check(!html.includes('id="reader-chinese-summary"'), 'No empty Chinese guide is emitted');
  equal(enriched,original,'Rendering does not rewrite source bibliography or insight');
  check(app.requests.every(call=>call.method==='GET'),'Reading, keyword filtering and searching never call a model');
}
async function insightRefreshPreservesNotes() {
  const enriched={...paper(1),insight:insightFixture()};
  const app=await setup('/papers/manage',[enriched]);
  await app.click('open-fixture',{open:identifier(1)});
  app.node('notes').value='An unsaved note';
  await app.node('detail').dispatch('input',{target:{id:'notes',value:'An unsaved note'}});
  app.setPapers([{...enriched,insight:{...enriched.insight,summary:{...enriched.insight.summary,overview:'更新后的中文导读。'},updated_at:'2026-11-21T01:00:00Z'}}]);
  await app.refresh();
  check(app.node('detail-content').innerHTML.includes('更新后的中文导读。'),'An insight timestamp change refreshes the already-open detail');
  check(app.node('detail-content').innerHTML.includes('An unsaved note'),'Insight refresh preserves unsaved management notes');
}

async function sessionRecoveryFlow() {
  let expired = false;
  const app = await setup('/papers/manage', [paper(1)], '#catalog', {
    stateResponse: () => expired ? response({error:{code:'feishu_login_required'}},401) : null
  });
  await app.click('open-fixture', {open:identifier(1)});
  app.node('notes').value = 'Unsaved research note';
  await app.node('detail').dispatch('input', {target:{id:'notes',value:app.node('notes').value}});
  expired = true;
  await app.refresh();
  const recovery = app.created.find(node=>node['aria-label']==='恢复飞书登录');
  check(recovery && !recovery.hidden, 'Expired Feishu session exposes the preserved recovery banner');
  check(!app.node('login').open, 'Feishu expiration does not open the separate password dialog');
  const login = recovery.querySelector('a');
  check(login.target === '_blank' && login.href.includes('return_to=%2Fpapers%2Fmanage%23catalog'), 'Recovery returns to the management route in a separate tab');
  equal(app.node('notes').value, 'Unsaved research note', 'Session expiration preserves the open note draft');
  expired = false;
  app.setPapers([{...paper(1),card:{...paper(1).card,updated_at:'2026-11-20'}}]);
  await recovery.querySelector('button').dispatch('click');
  check(recovery.hidden, 'Successful recovery clears the banner');
  check(app.node('detail-content').innerHTML.includes('Unsaved research note'), 'Re-render after recovery retains the note draft');
  check(app.requests.every(call=>call.method==='GET'), 'Session recovery does not submit drafts or start curation');
  const brokenPublic = await setup('/papers/', [paper(1)], '', {
    stateResponse: () => response({error:'temporarily unavailable'},401)
  });
  check(!brokenPublic.node('login').open && !brokenPublic.created.length, 'A catalog error never asks anonymous readers to authenticate');
}

async function publicReading(pathname) {
  const collection = [bibliography(1, 'Speech'), paper(2, 'Other')];
  const app = await setup(pathname, collection, '#catalog');
  const {node} = app;
  check(app.requests.every(call => call.url.endsWith('/api/catalog')), 'Public browsing only requests the public catalog');
  check(node('guide-button').hidden && node('settings-button').hidden && node('nav-workspace').hidden, 'Public shell hides management controls');
  check(!node('management-link').hidden && node('management-link').href.endsWith('/manage#workspace'), 'One management entry remains available');
  await app.route('#workspace');
  check(node('management').hidden && !node('discovery-view').hidden, 'A public workspace hash never exposes management');
  await app.click('settings-button');
  check(!node('provider-settings').open && !app.requests.some(call => call.url.endsWith('/settings')), 'Public settings events cannot load private configuration');
  await app.click('reading-fixture', {open:identifier(1)});
  const detail = node('detail-content').innerHTML;
  check(detail.includes('阅读 PDF 原文') && detail.includes('下载 PDF'), 'Imported bibliography can read and download existing originals');
  check(!detail.includes('团队权限') && !detail.includes('PAPER READING'), 'No obsolete permission or decorative reading labels');
  check(detail.includes('标题、作者与索引简介来自以下已有文献索引。'), 'Index metadata provenance remains in the detail');
  check(!detail.includes('id="notes"') && node('generate-reading').hidden, 'Public reader has no shared note editor or model action');
  check(!node('login').open, 'Opening literature never requests a library password');
  await app.click('favorite-fixture', {favorite:identifier(1)});
  await app.refresh();
  await app.route('#favorites');
  equal(idsIn(node('papers').innerHTML), [identifier(1)], 'Public favorites survive catalog refresh');
  check(!node('favorites-note').hidden, 'Favorites explain the browser-local storage');
  const revisited = await setup(pathname, collection, '#favorites', {storage:app.storage});
  equal(idsIn(revisited.node('papers').innerHTML), [identifier(1)], 'Browser favorites survive a new page session');
  await app.click('scan');
  await app.click('run');
  await app.click('generate-reading');
  check(app.requests.every(call => call.method === 'GET' && call.url.endsWith('/api/catalog')), 'Public actions never send private writes, state reads, or agent jobs');
  const missing = {...paper(3), available:false, fulltext_available:false};
  missing.card.doi = '10.1234/example';
  app.setPapers([missing]);
  await app.refresh();
  await app.route('#catalog');
  check(node('papers').innerHTML.includes('https://doi.org/10.1234%2Fexample'), 'Missing local original falls back to its recorded DOI');
  check(!node('papers').innerHTML.includes(`/papers/${missing.id}/pdf`), 'A missing original does not offer a broken local PDF');
}

(async () => {
  for (const pathname of ['/manage', '/papers/manage']) {
    await fullCollection(pathname);
    await initialLinksAndSmallCollections(pathname);
    await largeCollectionAndWorkspace(pathname);
    await providerDialog(pathname);
    await providerRaces(pathname);
  }
  for (const pathname of ['/', '/papers/']) await publicReading(pathname);
  await sessionRecoveryFlow();
  for (const pathname of ['/', '/papers/']) await insightReading(pathname);
  await insightRefreshPreservesNotes();
  console.log(`Discovery UI: ${checks} assertions passed.`);
})().catch(error => { console.error(error); process.exitCode = 1; });
