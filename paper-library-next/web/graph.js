/* Catalog-backed constellations. Grouping and camera movement carry no similarity score. */
(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  const svg = byId('graph-sphere');
  const NS = 'http://www.w3.org/2000/svg';
  const kinds = {direction: '方向', topic: '主题', byline: '作者署名', paper: '论文'};
  const sources = {'bibliography.category': '题录分类', 'card.category': '精读卡分类',
    'bibliography.tags': '题录标签', 'card.tags': '精读卡标签',
    'bibliography.authors': '题录作者栏', 'card.authors': '精读卡作者栏',
    'insight.keywords': '导读主题', 'insight.author_keywords.terms': '原文作者关键词'};
  const state = {nodes: new Map(), neighbors: new Map(), active: '', query: '', limit: 12,
    longitude: 0, latitude: 0, zoom: 1, points: [], lines: [], signature: null};
  let request = 0, fetchApi, catalogRows, drag = null;
  const compare = (a, b) => a.label.localeCompare(b.label, 'zh-CN') || a.id.localeCompare(b.id);
  const adjacency = n => state.neighbors.get(n.id) || [];
  const href = node => '#graph?' + new URLSearchParams({node: node.id});
  const clean = value => String(value).normalize('NFKC').toLocaleLowerCase().trim();
  function tag(name, attrs, parent = svg) {
    const element = document.createElementNS(NS, name);
    for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, String(value));
    parent.append(element);
    return element;
  }
  function bindGraph(data) {
    if (data?.schema_version !== 1 || !Array.isArray(data.nodes) || !Array.isArray(data.edges)) throw new Error('图谱格式无法读取');
    const nodes = new Map(data.nodes.map(n => [n.id, n])), neighbors = new Map();
    for (const edge of data.edges) {
      const left = nodes.get(edge.source), right = nodes.get(edge.target);
      if (!left || !right) continue;
      for (const [from, to] of [[left, right], [right, left]]) {
        if (!neighbors.has(from.id)) neighbors.set(from.id, []);
        neighbors.get(from.id).push({node: to, fields: edge.fields});
      }
    }
    state.nodes = nodes;
    state.neighbors = neighbors;
  }
  const phase = Math.PI * (3 - Math.sqrt(5));
  function spherePoint(i, size) {
    const y = size === 1 ? 0 : 1 - 2 * (i + .5) / size;
    const angle = i * phase, radial = Math.sqrt(1 - y * y);
    return [Math.sin(angle) * radial, y, Math.cos(angle) * radial];
  }
  function satellite(center, i, count, spread) {
    const [x, y, z] = center;
    const radial = Math.hypot(x, z) || 1;
    const u = [z / radial, 0, -x / radial], v = [-x * y / radial, radial, -z * y / radial];
    const arc = spread * Math.sqrt((i + 1) / count), a = i * phase;
    return center.map((c, j) => c * Math.cos(arc) + Math.sin(arc) * (u[j] * Math.cos(a) + v[j] * Math.sin(a)));
  }
  function layout(entries, focus, searching) {
    const points = new Map(), lines = [];
    const point = (n, xyz, label = false) => points.set(n.id, {node:n, xyz, label});
    if (focus && !searching) {
      point(focus, [0, 0, 1], true);
      const sample = entries.slice(0, 18);
      sample.forEach(({node}, i) => {
        point(node, sample.length === 1 ? [.78,-.21,.59] : spherePoint(i, sample.length), true);
        lines.push([focus.id, node.id]);
      });
    } else {
      const sample = entries.slice(0, searching ? 28 : 12);
      sample.forEach(({node}, i) => point(node, spherePoint(i, sample.length), true));
      if (searching) {
        sample.filter(({node}) => node.kind !== 'paper').forEach(({node}) => {
          adjacency(node).forEach(({node:other}) => { if (points.has(other.id)) lines.push([node.id, other.id]); });
        });
      } else {
        for (const {node} of sample) {
          if (node.kind === 'paper') continue;
          const children = adjacency(node).slice().sort((a,b) => compare(a.node,b.node)).slice(0, 4);
          children.forEach(({node: paper}, i) => {
            if (!points.has(paper.id)) point(paper, satellite(points.get(node.id).xyz, i, children.length, .31));
            lines.push([node.id, paper.id]);
          });
        }
      }
    }
    state.points = [...points.values()];
    state.lines = lines;
    const totalPapers = [...state.nodes.values()].filter(n => n.kind === 'paper').length;
    const drawnPapers = state.points.filter(p => p.node.kind === 'paper').length;
    byId('graph-sample').textContent = searching ? '图中显示 ' + state.points.length + ' 个匹配节点，完整结果可在列表中查看。' :
      focus ? '图中显示 ' + lines.length + ' / ' + entries.length + ' 条关联。' :
      '全库 ' + totalPapers + ' 篇论文，图中展示 ' + drawnPapers + ' 篇。选择节点可继续展开。';
    draw();
  }
  function project([x, y, z]) {
    const a = state.longitude, b = state.latitude;
    const zz = z * Math.cos(a) - x * Math.sin(a);
    const depth = zz * Math.cos(b) - y * Math.sin(b);
    const r = 140 * state.zoom;
    return {x: 240 + (x * Math.cos(a) + z * Math.sin(a)) * r,
      y: 190 - (y * Math.cos(b) + zz * Math.sin(b)) * r, z:depth};
  }
  function draw() {
    svg.replaceChildren();
    const r = 140 * state.zoom;
    tag('circle', {cx:240, cy:190, r, class:'sphere-rim'});
    for (const fraction of [.32, .7]) tag('ellipse', {cx:240, cy:190, rx:r, ry:r*fraction, class:'sphere-grid', transform:'rotate(-21 240 190)'});
    for (const fraction of [.38, .79]) tag('ellipse', {cx:240, cy:190, rx:r*fraction, ry:r, class:'sphere-grid', transform:'rotate(-21 240 190)'});
    const projected = new Map(state.points.map(p => [p.node.id, {...p, ...project(p.xyz)}]));
    for (const [from, to] of state.lines) {
      const a = projected.get(from), b = projected.get(to);
      tag('line', {x1:a.x, y1:a.y, x2:b.x, y2:b.y, class:'graph-link',
        opacity: (.45 + (a.z + b.z) * .12).toFixed(2)});
    }
    const ordered = [...projected.values()].sort((a,b) => a.z - b.z);
    for (const p of ordered) {
      const selected = p.node.id === state.active, radius = selected ? 7 : (p.node.kind === 'paper' ? 3.2 : 5.3) + (p.z + 1) * .6;
      const g = tag('g', {'data-node':p.node.id, class:'graph-star', opacity:(.69 + .31*(p.z+1)/2).toFixed(2)});
      tag('title', {}, g).textContent = kinds[p.node.kind] + ' · ' + p.node.label;
      tag('circle', {cx:p.x, cy:p.y, r:Math.max(10,radius*1.9), class:'star-hit'}, g);
      tag('circle', {cx:p.x, cy:p.y, r:radius, class:'star-' + p.node.kind}, g);
      if (selected) tag('circle', {cx:p.x, cy:p.y, r:12, class:'star-selection'}, g);
    }
    // Reserve a screen rectangle per label, including CJK widths. Full titles stay in the list.
    const boxes = [];
    const orderedLabels = ordered.filter(p => p.label).sort((a,b) => Number(b.node.id === state.active) - Number(a.node.id === state.active) || b.z-a.z);
    for (const p of orderedLabels) {
      const chars = Array.from(p.node.label), label = chars.length > 13 ? chars.slice(0,12).join('') + '…' : p.node.label;
      const scale = svg.clientWidth < 450 ? 1.5 : 1;
      const element = tag('text',{class:'star-label' + (scale > 1 ? ' compact-label' : ''), 'data-node':p.node.id});
      element.textContent=label;
      const width = element.getComputedTextLength();
      const x = Math.min(475-width, Math.max(4,p.x+10)), y = Math.max(15, Math.min(374,p.y-9));
      if (boxes.some(b => x < b.x+b.w+4 && x+width+4 > b.x && Math.abs(y-b.y)<16*scale)) { element.remove(); continue; }
      boxes.push({x,y,w:width});
      element.setAttribute('x', x); element.setAttribute('y', y);
    }
  }
  function update() {
    const focus = state.nodes.get(state.active);
    const term = clean(state.query);
    const list = [...state.nodes.values()];
    const count = kind => list.filter(n => n.kind === kind).length;
    byId('graph-count').textContent = count('paper') + ' 篇论文 · ' + count('direction') + ' 个方向 · ' + count('topic') + ' 个主题 · ' + count('byline') + ' 个署名';
    const dirs = list.filter(n => n.kind === 'direction');
    const topics = list.filter(n => n.kind === 'topic');
    let entries;
    if (term) {
      entries = list.filter(n => clean(n.label).includes(term)).sort((a,b) =>
        Number(clean(b.label) === term) - Number(clean(a.label) === term) || compare(a,b)).map(node => ({node}));
    } else if (focus) {
      const order = {direction:0, topic:1, byline:2, paper:3};
      entries = adjacency(focus).slice().sort((a,b) => order[a.node.kind]-order[b.node.kind] || compare(a.node,b.node));
    } else if (state.active && !focus) {
      entries = [];
    } else {
      const overview = dirs.length ? dirs : topics.length ? topics : list.filter(n => n.kind === 'paper');
      entries = overview.sort((a,b) => adjacency(b).length-adjacency(a).length || compare(a,b)).map(node => ({node}));
    }
    byId('graph-focus').textContent = term ? '搜索结果' : focus ? focus.label : state.active ? '该节点已不在目录中' : dirs.length ? '研究方向' : topics.length ? '研究主题' : '收录论文';
    byId('graph-back').hidden = !state.active && !term;
    const descriptions = {paper:'论文的分类、主题与原始署名。每条关系都列出来源字段。',
      byline:'以下论文的作者栏记录了这个署名。姓名顺序和合著字符串按原样保留，同名作者可能是不同的人。',
      direction:'这个研究方向收录了以下论文，每篇均列出分类依据。',topic:'以下论文记录了这个主题，列表标明各篇的主题来源。'};
    byId('graph-description').textContent = term ? '选择结果，查看它在库中的关联。' : focus ? descriptions[focus.kind] : state.active ? '可返回全库，或使用名称重新查找。' : '选择方向看论文，再沿作者署名或主题查找其他研究。';
    const reader = byId('graph-reader');
    reader.hidden = !!term || focus?.kind !== 'paper';
    if (!reader.hidden) reader.dataset.open = focus.id;
    else delete reader.dataset.open;
    const shown = entries.slice(0, state.limit);
    const result = byId('graph-results');
    result.replaceChildren();
    for (const {node, fields} of shown) {
      const li = document.createElement('li'), link = document.createElement('a'), note = document.createElement('small');
      link.href = href(node); link.textContent = node.label;
      const detail = fields ? fields.map(f => sources[f] || f).join('、') : node.kind === 'paper' ? (node.year || '年份待核对') : adjacency(node).length + ' 篇论文';
      note.textContent = kinds[node.kind] + ' · ' + detail;
      li.append(link, note); result.append(li);
    }
    byId('graph-status').textContent = !entries.length ? (term ? '没有匹配的节点。' : focus ? '暂无可追溯的关联。' : state.active ? '' : '暂无可展示的文献。') : '列表显示 ' + shown.length + ' / ' + entries.length + ' 项';
    byId('graph-more').hidden = shown.length >= entries.length;
    layout(entries, focus, !!term);
  }
  function route() {
    const node = new URLSearchParams(location.hash.split('?')[1] || '').get('node') || '';
    if (node !== state.active || (state.query && !node && location.hash === '#graph' && byId('graph-back') === document.activeElement)) {
      state.active = node;
      state.query = byId('graph-query').value = '';
      state.limit = 12;
      resetCamera();
      return true;
    }
    return false;
  }
  function resetCamera() { state.longitude=0; state.latitude=0; state.zoom=1; }
  async function show(api, rows, force = false) {
    fetchApi = api; catalogRows = rows;
    const changed = route();
    const sig = JSON.stringify(rows.map(p => [p.id,p.updated,p.insight?.updated_at,p.bibliography?.imported_at]));
    if (!force && state.signature === sig) { if (changed && !state.loading) update(); return; }
    state.signature=sig; state.loading=true;
    const serial = ++request;
    byId('graph-retry').hidden=true;
    byId('graph-status').textContent='正在读取文献关系…';
    try {
      const data = await api('/api/graph');
      if (serial !== request) return;
      bindGraph(data); state.loading=false; route(); update();
    } catch (error) {
      if (serial !== request) return;
      state.loading=false; state.signature=null;
      byId('graph-status').textContent='文献图谱读取失败。' + error.message;
      byId('graph-retry').hidden=false;
    }
  }
  function zoom(delta) { state.zoom=Math.max(.65,Math.min(1.85,state.zoom+delta)); draw(); }
  byId('graph-query').addEventListener('input', e => {state.query=e.target.value; state.limit=12; if (!state.loading) update();});
  byId('graph-results').addEventListener('click', e => {
    const link=e.target.closest('a');
    if (state.query && link?.hash === location.hash) { state.query=byId('graph-query').value=''; state.limit=12; update(); byId('graph-title').focus(); }
  });
  byId('graph-back').addEventListener('click', () => { state.query=byId('graph-query').value=''; state.limit=12; if (location.hash==='#graph') update(); });
  byId('graph-more').addEventListener('click', () => {const start=state.limit; state.limit+=12; update(); byId('graph-results').children[start]?.querySelector('a')?.focus();});
  byId('graph-reset').addEventListener('click', () => {resetCamera(); draw();});
  byId('graph-larger').addEventListener('click', () => zoom(.15));
  byId('graph-smaller').addEventListener('click', () => zoom(-.15));
  byId('graph-retry').addEventListener('click', () => show(fetchApi,catalogRows,true));
  svg.addEventListener('pointerdown', e => { if (e.button !== 0) return;
    drag={id:e.pointerId,x:e.clientX,y:e.clientY,moved:false,node:e.target.closest('[data-node]')?.dataset.node};
    svg.setPointerCapture(e.pointerId); });
  svg.addEventListener('pointermove', e => { if (drag?.id !== e.pointerId) return;
    const dx=e.clientX-drag.x, dy=e.clientY-drag.y;
    if (!drag.moved && Math.abs(dx)+Math.abs(dy)<4) return;
    drag.moved=true; drag.x=e.clientX; drag.y=e.clientY;
    state.longitude+=dx*.014; state.latitude=Math.max(-1.45,Math.min(1.45,state.latitude-dy*.014)); draw();
  });
  svg.addEventListener('pointerup', e => { if (drag?.id !== e.pointerId) return;
    if (!drag.moved && drag.node) location.hash=href(state.nodes.get(drag.node));
    drag=null; });
  svg.addEventListener('pointercancel', () => {drag=null;});
  svg.addEventListener('keydown', e => {
    if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-','Home'].includes(e.key)) return;
    e.preventDefault();
    if (e.key === '+' || e.key === '=') return zoom(.15);
    if (e.key === '-') return zoom(-.15);
    if (e.key === 'Home') resetCamera();
    if (e.key === 'ArrowLeft') state.longitude-=.17;
    if (e.key === 'ArrowRight') state.longitude+=.17;
    if (e.key === 'ArrowUp') state.latitude=Math.min(1.45,state.latitude+.17);
    if (e.key === 'ArrowDown') state.latitude=Math.max(-1.45,state.latitude-.17);
    draw();
  });
  window.LiteratureGraph = {show};
})();
