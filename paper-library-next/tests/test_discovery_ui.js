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
  result.fulltext_available = false;
  return result;
}
const stateFor = papers => ({papers, jobs: [], agent: {configured: false, enabled: false},
  running: false, inbox: '/fixture/inbox'});
const idsIn = html => [...new Set([...html.matchAll(/data-open="([a-f0-9]{64})"/g)].map(match => match[1]))];
const flush = () => new Promise(resolve => setImmediate(resolve));

async function setup(pathname, papers, hash = '') {
  let serverState = stateFor(clone(papers));
  const nodes = new Map(), documentHandlers = new Map(), windowHandlers = new Map();
  const requests = [], timers = new Map(), visits = [];
  let timer = 0, seed = 391;
  const document = {hidden: false, activeElement: {tagName: 'BODY'}};
  const node = id => {
    if (!nodes.has(id)) {
      const events = new Map(), classes = new Set();
      let html = '', text = '';
      const element = {id, value: id === 'sort' ? 'newest' : '', checked: false, hidden: false,
        open: false, disabled: false, scrollTop: 0, dataset: {}, tagName: 'DIV',
        get innerHTML() { return html; }, set innerHTML(value) { html = String(value); },
        get textContent() { return text; }, set textContent(value) { text = String(value); },
        insertAdjacentHTML(position, value) { html += value; },
        setAttribute(name, value) { this[name] = String(value); },
        classList: {add(name) { classes.add(name); }, remove(name) { classes.delete(name); },
          toggle(name, value) { if (value) classes.add(name); else classes.delete(name); }},
        addEventListener(name, handler) { events.set(name, handler); },
        async dispatch(name, event = {}) { if (events.has(name)) await events.get(name)(event); },
        showModal() { this.open = true; },
        close() { this.open = false; if (events.has('close')) events.get('close')(); },
        focus() { document.activeElement = this; }, scrollIntoView() {}, appendChild() {}};
      nodes.set(id, element);
    }
    return nodes.get(id);
  };
  document.getElementById = node;
  document.querySelector = selector => selector === '.agent-state' ? node('agent-state') :
    selector === 'dialog[open]' ? ['detail', 'guide', 'login'].map(node).find(item => item.open) || null : null;
  document.querySelectorAll = () => [];
  document.addEventListener = (name, handler) => documentHandlers.set(name, handler);
  document.body = node('body');
  const location = {pathname, hash};
  const window = {location, addEventListener: (name, handler) => windowHandlers.set(name, handler),
    history: {pushState(data, title, url) { visits.push(url); location.hash = url; },
      replaceState(data, title, url) { location.hash = url; }}};
  const math = Object.create(Math);
  math.random = () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; };
  const fetch = async (url, options = {}) => {
    requests.push({url, method: options.method || 'GET'});
    const apiPath = url.replace(/^\/papers(?=\/api\/)/, '');
    if (apiPath === '/api/state' && !options.method) {
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
  return {node, requests, visits, location, click, route,
    async refresh() { await node('refresh').onclick(); await flush(); },
    async submitSearch(value) { node('discovery-search').value = value;
      node('discovery-search-form').onsubmit({preventDefault() {}}); await flush(); },
    async inputSearch(value) { node('search').value = value; await node('search').dispatch('input');
      for (const [id, callback] of [...timers]) { timers.delete(id); callback(); } await flush(); },
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
  check(node('papers').innerHTML.includes('题录已导入 · 待原文核验'), 'Bibliography label survives category view');
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
  check(app.requests.every(call => call.url.startsWith(pathname === '/papers/' ? '/papers/api/' : '/api/')), 'API base remains correct for both deployments');
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

(async () => {
  for (const pathname of ['/', '/papers/']) {
    await fullCollection(pathname);
    await initialLinksAndSmallCollections(pathname);
  }
  console.log(`Discovery UI: ${checks} assertions passed.`);
})().catch(error => { console.error(error); process.exitCode = 1; });
