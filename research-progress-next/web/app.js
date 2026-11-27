'use strict';
const $ = id => document.getElementById(id);
const keys = ['done','results','blockers','next'];
let config, busy = false, teamEpoch = 0, knowledgeEpoch = 0, directionEpoch = 0;
let selectedWeek;
let selectedMember;
let teamWeeks = [];
let directionFocusHash;
let uploadStatusEpoch = 0, uploadStatusTimer;
let submittedDailySnapshot, submittedWeeklySnapshot;
let sessionRecoveryBusy = false;
const sessionExpiredMessage = '飞书登录已过期。请在新标签中重新登录，然后返回这里继续。';
function updateSessionLogin() {
  const login = new URL('/auth/login', location.origin);
  login.searchParams.set('return_to', location.pathname + location.search + location.hash);
  $('session-login').href = login.href;
}
function requireSession() {
  updateSessionLogin();
  $('session-recovery').hidden = false;
  $('session-recovery-message').textContent = sessionExpiredMessage;
  teamActivity.stop();
  stopUploadStatus();
}
const lastMemberKey = 'research-progress:last-submitted-member';
function lastSubmittedMember() {
  try { return localStorage.getItem(lastMemberKey); } catch { return null; }
}
function rememberSubmittedMember(id) {
  if (!config?.members.some(member => member.id === id)) return;
  try { localStorage.setItem(lastMemberKey, id); } catch { /* The current submission still succeeds. */ }
}
function sameSnapshot(current, saved) {
  return saved && current.length === saved.length && current.every((value, index) => value === saved[index]);
}
function weeklySnapshot() {
  return [$('member').value, $('week').value, $('report-file').files[0] || null];
}
function dailySnapshot() {
  return [dailyMode, $('daily-member').value, $('daily-date').value,
    ...keys.map(key => $('daily-field-' + key).value), $('daily-file').files[0] || null,
    ...$('daily-attachments').files];
}
const uploadStatusLabels = {
  queued:'已收原件，排队等待整理',
  processing:'已收原件，正在整理',
  ready:'已整理，可以进入周报汇总',
  needs_review:'待整理，需要维护人员检查',
  failed:'整理失败'
};
function feedback(message, error = false) {
  $('upload-feedback').textContent = message;
  $('upload-feedback').classList.toggle('error', error);
}
function stopUploadStatus() {
  uploadStatusEpoch++;
  clearTimeout(uploadStatusTimer);
  uploadStatusTimer = null;
}
function showUploadStatus(status, detail, prefix = '') {
  const message = uploadStatusLabels[status] || '正在确认汇总状态';
  feedback(prefix + message + (detail ? `：${detail}` : ''), status === 'failed' || status === 'needs_review');
}
async function pollUploadStatus(s, epoch) {
  try {
    const result = await api('/api/upload-status?'+new URLSearchParams(s));
    if (epoch !== uploadStatusEpoch) return;
    showUploadStatus(result.status, result.status_detail);
    if (result.status === 'queued' || result.status === 'processing') {
      uploadStatusTimer = setTimeout(() => pollUploadStatus(s, epoch), 2000);
    }
  } catch(e) {
    if (epoch === uploadStatusEpoch) feedback('周报已上传，但状态查询失败：'+e.message, true);
  }
}
function startUploadStatus(s, result) {
  stopUploadStatus();
  const epoch = uploadStatusEpoch;
  const status = result.summary_status || 'queued';
  const prefix = `${result.duplicate ? '该内容已提交，无需重复保存' : '周报提交成功'}：${result.member_id} · ${result.week}。`;
  showUploadStatus(status, result.status_detail, prefix);
  if (status === 'queued' || status === 'processing') {
    uploadStatusTimer = setTimeout(() => pollUploadStatus(s, epoch), 2000);
  }
}
async function api(path, options = {}) {
  const r = await fetch(path.replace(/^\//, ''), {cache:'no-store', ...options});
  const data = await r.json().catch(() => null);
  if (!r.ok) {
    if (r.status === 401 && data?.error === 'feishu_login_required') {
      requireSession();
      throw Object.assign(new Error(sessionExpiredMessage), {status: r.status, code: 'feishu_login_required'});
    }
    const detail = typeof data?.error === 'string' ? data.error.trim() : '';
    let message = detail || `请求失败（HTTP ${r.status}），请稍后重试。`;
    if (r.status === 413) {
      const reason = (detail || '文件超过当前入口的上传限制').replace(/[。.!！]$/, '');
      message = `${reason}。请缩小文件后重试。`;
    }
    throw Object.assign(new Error(message), {status: r.status});
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('服务返回了无法读取的响应，请稍后重试。');
  return data;
}
function button(label, action, cls = 'team-index-item') {
  const b = document.createElement('button'); b.type = 'button'; b.className = cls; b.textContent = label;
  b.addEventListener('click', () => Promise.resolve().then(action).catch(e => toast(e.message))); return b;
}
function toast(message) {
  $('toast').textContent = message; $('toast').hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => {$('toast').hidden = true;}, 6000);
}
function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], {type:'text/markdown;charset=utf-8'}));
  const a = document.createElement('a'); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function node(tag, value, className) {
  const element = document.createElement(tag);
  if (value !== undefined) element.textContent = value;
  if (className) element.className = className;
  return element;
}
function inlineMarkdown(root, text) {
  let cursor = 0;
  for (const m of text.matchAll(/\[([^\]\n]+)\]\(([^\s)]+)\)/g)) {
    root.append(text.slice(cursor, m.index));
    const clean = !/[\u0000-\u001f\u007f\\]/.test(m[2]);
    if (clean && (/^https?:\/\//i.test(m[2]) || /^\/(?!\/)/.test(m[2]))) {
      const a = node('a', m[1]);
      a.href = m[2];
      root.append(a);
    } else {
      root.append(m[0]);
    }
    cursor = m.index + m[0].length;
  }
  root.append(text.slice(cursor));
}
function markdown(root, text, headingOffset = 1) {
  root.replaceChildren(); root.classList.add('markdown');
  let list;
  for (const line of text.split(/\r?\n/)) {
    const h = /^(#{1,4}) (.*)$/.exec(line);
    if (line.startsWith('- ')) {
      if (!list) {list = node('ul'); root.append(list);}
      const item = node('li'); inlineMarkdown(item, line.slice(2)); list.append(item); continue;
    }
    list = null;
    if (!line.trim()) continue;
    const block = node(h ? 'h'+Math.min(6, h[1].length + headingOffset) : 'p');
    inlineMarkdown(block, h ? h[2] : line);
    root.append(block);
  }
}
function selection() {
  if (!$('member').value || !$('week').value) throw new Error('请先选择成员与报告周次');
  return {member_id:$('member').value, week:$('week').value};
}
function updateReady() {
  $('submit-report').disabled = busy || !config || !$('member').value || !$('week').value;
}
['member','week'].forEach(id => $(id).addEventListener('change', () => {stopUploadStatus(); feedback(''); updateReady();}));
$('download-template').onclick = async () => {
  try {const s=selection(); const t = await api('/api/report-template?'+new URLSearchParams(s)); download(t.filename, t.markdown);}
  catch(e) {feedback(e.message,true);}
};
$('report-file').onchange = () => {
  stopUploadStatus(); feedback('');
  const file = $('report-file').files[0]; if (!file) return;
  if (config && file.size > config.max_upload_bytes) {
    $('report-file').value=''; feedback('文件超出上传大小限制', true); return;
  }
  feedback(`已选择 ${file.name}，提交后将显示整理状态。`);
};
$('report-form').onsubmit = async event => {
  event.preventDefault(); if(busy) return;
  try {
    const s=selection();
    const file=$('report-file').files[0]; if(!file) throw new Error('请选择周报文件');
    const form=new FormData(); form.append('member_id',s.member_id); form.append('week',s.week); form.append('file',file);
    const options={method:'POST',headers:{'X-Requested-With':'ResearchWeekly'},body:form};
    const snapshot = weeklySnapshot();
    stopUploadStatus();
    busy=true; updateReady(); $('member').disabled=true; $('week').disabled=true;
    feedback('正在上传并校验周报文件…');
    const result=await api('/api/uploads',options);
    submittedWeeklySnapshot = snapshot;
    rememberSubmittedMember(s.member_id);
    startUploadStatus(s,result);
  } catch(e) {feedback(e.message,true);}
  finally {busy=false; $('member').disabled=false; $('week').disabled=false; updateReady();}
};
function contentList(items, className) {
  const list = node('ul', undefined, className);
  for (const value of items ?? []) {
    const item = node('li');
    inlineMarkdown(item, value);
    list.append(item);
  }
  return list;
}
function titledList(title, items, className) {
  const section = node('section', undefined, className);
  section.append(node('h3', title));
  if (items?.length) section.append(contentList(items));
  else section.append(node('p', '本周汇总未记录此项。', 'muted'));
  return section;
}
function dateLabel(date) {
  if (!date) return '';
  const value = new Date(date);
  if (date.length <= 10 || Number.isNaN(value.valueOf())) return date;
  return value.toLocaleString('zh-CN', {dateStyle:'medium', timeStyle:'short', timeZone:config?.timezone ?? 'Asia/Shanghai'});
}
function selectWeek(week) {
  const hash = teamActivity.weekRoute(week);
  $('weekly-archive').open = true;
  if (location.hash === hash) loadTeam(week);
  else location.hash = hash;
}
function renderWeeks(activeWeek = selectedWeek) {
  $('team-list').replaceChildren();
  for (const row of teamWeeks) {
    const weekButton = button('', () => selectWeek(row.week));
    weekButton.append(node('strong', row.week), node('span', `${row.submitted} / ${row.expected} 份已汇总`));
    if (row.week === activeWeek) weekButton.setAttribute('aria-current', 'true');
    $('team-list').append(weekButton);
  }
}
function renderMembers(doc) {
  const section = node('section', undefined, 'panel member-panel');
  const header = node('div', undefined, 'panel-heading');
  header.append(node('h2', '成员周报摘要'));
  const people = doc.members;
  if (!people.length) {
    section.append(header, node('p', '本周暂无成员摘要。', 'empty'));
    return section;
  }
  const filterLabel = node('label', '查看成员', 'member-filter');
  const picker = node('select');
  picker.append(new Option('全部成员', ''));
  people.forEach(person => picker.append(new Option(person.name, person.id)));
  if (selectedMember && !people.some(person => person.id === selectedMember)) {
    picker.append(new Option('所选成员暂无摘要', selectedMember));
  }
  if (selectedMember) picker.value = selectedMember;
  filterLabel.append(picker);
  header.append(filterLabel);
  section.append(header);
  const grid = node('div', undefined, 'member-grid');
  section.append(grid);
  const fields = [['done', '本周完成'], ['results', '结果与证据'], ['blockers', '问题与阻塞'], ['next', '下周计划']];
  function renderPeople() {
    grid.replaceChildren();
    for (const person of people) {
      if (picker.value && picker.value !== person.id) continue;
      const card = node('article', undefined, 'member-card');
      const name = node('h3', person.name);
      card.append(name);
      const detail = node('dl', undefined, 'member-details');
      for (const [key, label] of fields) {
        const values = person[key];
        const body = node('dd');
        if (values?.length) body.append(contentList(values));
        else body.append(node('p', '未说明', 'muted'));
        detail.append(node('dt', label), body);
      }
      card.append(detail);
      const source = typeof person.source_sha256 === 'string' ? ` · 来源校验 ${person.source_sha256.slice(0, 12)}` : '';
      const provenance = node('p', undefined, 'record-source');
      provenance.append(node('span', `来源 ${doc.week} 周报${source}`));
      const original = node('a', '阅读周报正文与原件', 'text-link member-report-link');
      original.href = '#team?' + new URLSearchParams({week:doc.week, member:person.id, report:'weekly'});
      provenance.append(original);
      card.append(provenance);
      grid.append(card);
    }
    if (!grid.childElementCount) grid.append(node('p', '所选成员在本周暂无已发布的周报摘要。', 'muted'));
  }
  picker.addEventListener('change', () => {
    selectedMember = picker.value;
    renderPeople();
  });
  renderPeople();
  return section;
}
function renderTeam(doc) {
  const reader = $('team-reader');
  const hero = node('header', undefined, 'panel report-overview');
  const title = node('div', undefined, 'report-title');
  const copy = node('div');
  copy.append(node('p', doc.date_range?.join(' 至 ') || '', 'record-date'), node('h2', `${doc.week} 团队周报`));
  title.append(copy);
  if (typeof doc.markdown === 'string') {
    title.append(button('下载 Markdown ↓', () => download(doc.week + '.md', doc.markdown), 'text-link'));
  }
  hero.append(title);
  const scope = Number.isFinite(doc.submitted) ? `依据 ${doc.submitted} 份周报` : '';
  hero.append(node('p', [doc.engine_label, dateLabel(doc.generated_at), scope].filter(Boolean).join(' · '), 'record-source'));
  reader.replaceChildren(hero);
  if (!Array.isArray(doc.members)) {
    if (typeof doc.markdown === 'string') {
      const legacy = node('div', undefined, 'panel document-panel');
      markdown(legacy, doc.markdown);
      reader.append(legacy);
    }
    return;
  }
  reader.append(titledList('本周概要', doc.overview, 'panel summary-panel'));
  reader.append(renderMembers(doc));
  const followUp = node('div', undefined, 'follow-up');
  followUp.append(titledList('需要协助', doc.team_risks, 'panel summary-panel'), titledList('后续安排', doc.next_actions, 'panel summary-panel'));
  reader.append(followUp);
}
async function showTeam(week) {
  const epoch = ++teamEpoch;
  const reader = $('team-reader');
  reader.setAttribute('aria-busy', 'true');
  reader.replaceChildren(node('p', `正在读取 ${week} 周报。`, 'panel empty'));
  try {
    const doc = await api('/api/team/' + encodeURIComponent(week));
    if (epoch !== teamEpoch) return;
    selectedWeek = week;
    renderWeeks();
    renderTeam(doc);
  } catch (error) {
    if (epoch !== teamEpoch) return;
    renderWeeks(null);
    reader.replaceChildren(node('p', `${week} 周报读取失败。${error.message}`, 'panel empty'));
  } finally {
    if (epoch === teamEpoch) reader.removeAttribute('aria-busy');
  }
}
function renderMissingWeek(requestedWeek) {
  renderWeeks(null);
  const empty = node('section', undefined, 'panel document-panel');
  const validFormat = /^\d{4}-W(?:0[1-9]|[1-4]\d|5[0-3])$/.test(requestedWeek);
  const latest = teamWeeks[0]?.week;
  const title = validFormat ? `${requestedWeek} 暂无团队周报` : requestedWeek === null ? '暂无团队周报' : '周次链接无效';
  const hint = latest ? '可从周报归档选择已发布的周次。' : '团队汇总生成后会按周出现在这里。';
  empty.append(node('h2', title), node('p', hint));
  const link = node('a', latest ? '查看最新周报 ↗' : '查看研究方向 ↗', 'text-link');
  link.href = latest ? '#team?' + new URLSearchParams({week: latest}) : '#directions';
  empty.append(link);
  $('team-reader').replaceChildren(empty);
}
async function loadTeam(requestedWeek) {
  const epoch = ++teamEpoch;
  const reader = $('team-reader');
  reader.setAttribute('aria-busy', 'true');
  if (requestedWeek !== null && requestedWeek !== selectedWeek) {
    reader.replaceChildren(node('p', '正在查询周报归档。', 'panel empty'));
  }
  try {
    const data = await api('/api/team');
    if (epoch !== teamEpoch) return;
    teamWeeks = data.items;
    teamActivity.setArchive(teamWeeks);
    const week = requestedWeek ?? (teamWeeks.some(item => item.week === selectedWeek) ? selectedWeek : teamWeeks[0]?.week);
    if (teamWeeks.some(item => item.week === week)) await showTeam(week);
    else renderMissingWeek(requestedWeek);
  } catch (error) {
    if (epoch === teamEpoch) {
      reader.replaceChildren(node('p', '团队周报暂未读取成功。' + error.message, 'panel empty'));
    }
  } finally {
    if (epoch === teamEpoch) reader.removeAttribute('aria-busy');
  }
}
async function loadDirections(selectedId, focusHash) {
  const root = $('direction-list');
  const epoch = ++directionEpoch;
  const detail = selectedId !== null;
  const status = node('p', '正在读取研究方向。', 'empty');
  root.replaceChildren(status);
  if (detail) {
    const back = node('a', '← 全部研究方向', 'text-link directions-back');
    back.href = '#directions';
    root.prepend(back);
  }
  if (detail && !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(selectedId)) {
    status.textContent = '未找到这份研究方向文档。';
    return;
  }
  try {
    const data = await api(detail ? '/api/directions/' + encodeURIComponent(selectedId) : '/api/directions');
    if (epoch !== directionEpoch) return;
    const items = detail ? [data] : data.items;
    for (const item of items) {
      const card = node('article', undefined, 'panel direction-card');
      const header = node('header');
      const title = node('h2');
      if (detail) {
        title.textContent = item.title;
        title.tabIndex = -1;
      } else {
        const link = node('a', item.title);
        link.href = '#directions?' + new URLSearchParams({item:item.id});
        title.append(link);
      }
      header.append(title);
      const meta = [item.updated_at && `核对于 ${item.updated_at}`, item.lead && `负责人 ${item.lead}`].filter(Boolean);
      if (meta.length) header.append(node('p', meta.join(' · '), 'record-source'));
      card.append(header);
      const parts = [['question', '研究问题'], ['progress', '当前进展'], ['next', '下一步']];
      if (detail) {
        const body = node('div');
        const paragraphs = item.markdown.trim().split(/\r?\n/);
        paragraphs.shift();
        markdown(body, paragraphs.join('\n').replace(/^((?:核对日期|负责人)[：:].*\r?\n)/gm, ''));
        card.append(body);
      } else {
        for (const [field, label] of parts) {
          if (!item[field]) continue;
          const section = node('section', undefined, 'direction-part');
          section.append(node('h3', label));
          const body = node('div');
        markdown(body, item[field], 3);
          section.append(body);
          card.append(section);
        }
      }
      if (!detail && item.evidence) {
        const details = node('details', undefined, 'direction-detail');
        details.append(node('summary', '来源与范围'));
        const body = node('div');
        markdown(body, item.evidence, 2);
        details.append(body);
        card.append(details);
      }
      root.append(card);
    }
    if (!items.length) root.append(node('p', '暂无研究方向记录。', 'empty'));
    if (data.unavailable?.length) root.append(node('p', `待核对的方向文档 ${data.unavailable.join('、')}`, 'empty'));
    status.remove();
    if (focusHash === location.hash && document.activeElement === document.body) {
      const title = root.querySelector('.direction-card h2');
      title.focus({preventScroll:true});
      title.scrollIntoView({block:'start',behavior:'instant'});
    }
  } catch (error) {
    if (epoch !== directionEpoch) return;
    const missing = detail && error.status === 404;
    status.textContent = missing ? '未找到这份研究方向文档。' : '暂时无法读取研究方向。';
    if (!missing) status.after(button('重试', () => loadDirections(selectedId), 'text-link'));
  }
}
async function loadKnowledge() {
  const epoch = ++knowledgeEpoch;
  const data = await api('/api/knowledge');
  if (epoch !== knowledgeEpoch) return;
  const grid = $('knowledge-grid');
  const reader = $('knowledge-reader');
  grid.replaceChildren();
  reader.hidden = true;
  async function showArticle(row, target) {
    const request = ++knowledgeEpoch;
    const doc = await api('/api/knowledge/' + encodeURIComponent(row.name));
    if (request !== knowledgeEpoch) return;
    for (const card of grid.children) card.setAttribute('aria-pressed', card === target);
    markdown(reader, doc.content);
    reader.hidden = false;
  }
  if (data.items[0]?.name === 'README.md') {
    await showArticle(data.items[0]);
  }
  for (const row of data.items) {
    if (row.name === 'README.md' && data.items.length === 1) continue;
    const tile = button('', () => showArticle(row, tile), 'knowledge-card');
    tile.append(node('strong', row.title));
    if (row.excerpt) tile.append(node('span', row.excerpt));
    tile.setAttribute('aria-pressed', row.name === 'README.md');
    grid.append(tile);
  }
  if (!data.items.length) grid.append(node('p', '暂无共读说明。', 'empty'));
}
async function renderRoute() {
  const focusHash = directionFocusHash === location.hash ? directionFocusHash : undefined;
  directionFocusHash = undefined;
  const [slug, query] = location.hash.slice(1).split('?');
  if (slug === 'main-content') return;
  const view = ['daily', 'upload', 'directions', 'knowledge'].includes(slug) ? slug : 'team';
  if (view !== 'team') teamActivity.stop();
  document.querySelectorAll('.view').forEach(section => section.hidden = section.id !== 'view-' + view);
  document.querySelectorAll('[data-view]').forEach(link => {
    if (link.dataset.view === view) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  $('registration-panel').hidden = !['daily', 'upload'].includes(view);
  const heading = document.querySelector('#view-' + view + ' h1');
  document.title = `${heading.textContent} · 科研管理平台`;
  try {
    if (view === 'team') {
      const params = new URLSearchParams(query);
      const activity = await teamActivity.open(params);
      if ($('view-team').hidden || location.hash.slice(1).split('?')[1] !== query) return;
      selectedMember = teamActivity.weeklyMember() || undefined;
      await loadTeam(activity?.week ?? params.get('week'));
    }
    if (view === 'directions') await loadDirections(new URLSearchParams(query).get('item'), focusHash);
    if (view === 'knowledge') await loadKnowledge();
  } catch (error) {
    toast(error.message);
  }
}
$('direction-list').addEventListener('click', event => {
  const link = event.target.closest('.direction-card h2 a');
  if (!link || event.button !== 0 || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
  directionFocusHash = link.hash;
});
window.addEventListener('hashchange', renderRoute);
window.addEventListener('hashchange', () => {
  if (!$('session-recovery').hidden) updateSessionLogin();
});
$('refresh-team').onclick=()=>{
  teamActivity.refresh();
  return loadTeam(teamActivity.week() || selectedWeek || null);
};
window.addEventListener('beforeunload', e=>{
  const dailyDirty = submittedDailySnapshot ? !sameSnapshot(dailySnapshot(), submittedDailySnapshot)
    : keys.some(key => $('daily-field-' + key).value.trim()) || $('daily-file').files.length || $('daily-attachments').files.length;
  const weeklyDirty = submittedWeeklySnapshot ? !sameSnapshot(weeklySnapshot(), submittedWeeklySnapshot)
    : $('report-file').files.length;
  if (busy || dailyBusy || dailyDirty || weeklyDirty) { e.preventDefault(); e.returnValue = ''; }
});
let dailyMode='form', dailyBusy=false, dailyFileEpoch=0, registrationBusy=false;
function dailyFeedback(message,error=false){
  $('daily-feedback').textContent=message;
  $('daily-feedback').classList.toggle('error',error);
  $('daily-team-link').hidden=true;
}
function dailyReady(){$('daily-submit').disabled=dailyBusy || !config || !$('daily-member').value || !$('daily-date').value;}
function dailySelection(){
  if(!$('daily-member').value || !$('daily-date').value)throw new Error('请先选择成员与日报日期');
  return {member_id:$('daily-member').value,date:$('daily-date').value};
}
function setDailyMode(value){
  if(dailyBusy)return;
  dailyMode=value; $('daily-fields-panel').hidden=value!=='form'; $('daily-file-panel').hidden=value!=='file';
  keys.forEach(k=>{$('daily-field-'+k).disabled=value!=='form';}); $('daily-file').required=value==='file';
  $('daily-mode-form').classList.toggle('active',value==='form'); $('daily-mode-file').classList.toggle('active',value==='file');
  $('daily-mode-form').setAttribute('aria-pressed', value === 'form'); $('daily-mode-file').setAttribute('aria-pressed', value === 'file'); dailyFeedback('');
}
$('daily-mode-form').onclick=()=>setDailyMode('form'); $('daily-mode-file').onclick=()=>setDailyMode('file');
['daily-member','daily-date'].forEach(id=>$(id).addEventListener('change',()=>{dailyFeedback('');dailyReady();}));
$('daily-download-template').onclick=async()=>{
  try{const t=await api('/api/daily-template?'+new URLSearchParams(dailySelection()));download(t.filename,t.markdown);}
  catch(e){dailyFeedback(e.message,true);}
};
const dailyTextExtensions=/\.(md|markdown|txt|csv)$/i;
const dailyMarkdownExtensions=/\.(md|markdown)$/i;
function validateDailyFile(file){
  if(!/\.(md|markdown|txt|csv|docx|xlsx|pptx|pdf)$/i.test(file.name))throw new Error('该格式可放在附件栏。正文支持 Markdown、文本、CSV、Office 和 PDF');
  const limit=dailyMarkdownExtensions.test(file.name) ? config.max_report_bytes : config.max_daily_attachment_bytes;
  if(file.size>limit)throw new Error('日报文件超出大小限制');
  if(!file.size)throw new Error('日报文件不能为空');
}
$('daily-file').onchange=async()=>{
  const epoch=++dailyFileEpoch; $('daily-file-preview').hidden=true; dailyFeedback('');
  const file=$('daily-file').files[0]; if(!file)return;
  try{
    validateDailyFile(file);
    if(!dailyTextExtensions.test(file.name))return;
    const text=new TextDecoder('utf-8',{fatal:true}).decode(await file.slice(0,65536).arrayBuffer(),{stream:file.size>65536}); if(epoch!==dailyFileEpoch)return;
    $('daily-file-preview').textContent=text; $('daily-file-preview').hidden=false;
  }catch(e){if(epoch===dailyFileEpoch){$('daily-file').value='';dailyFeedback(e.message,true);}}
};
function selectedDailyAttachments(){
  const files=[...$('daily-attachments').files];
  if(files.length > config.max_daily_attachments)throw new Error(`最多选择 ${config.max_daily_attachments} 个日报附件`);
  if(files.reduce((total,file)=>total+file.size,0) > config.max_daily_attachment_bytes)throw new Error('日报附件总大小超出限制');
  if(files.some(file=>!file.size))throw new Error('日报附件不能为空');
  return files;
}
$('daily-attachments').onchange=()=>{
  const list=$('daily-attachment-list');
  list.replaceChildren();
  list.hidden=true;
  dailyFeedback('');
  try{
    const files=selectedDailyAttachments();
    for(const file of files){
      const item=document.createElement('li');
      item.textContent=file.name;
      list.append(item);
    }
    list.hidden=!files.length;
  }catch(e){dailyFeedback(e.message,true);}
};
$('daily-form').onsubmit=async event=>{
  event.preventDefault(); if(dailyBusy)return;
  try{
    const s=dailySelection(),options={method:'POST',headers:{'X-Requested-With':'ResearchWeekly'}};
    const attachments=selectedDailyAttachments();
    const fields=dailyMode==='form' ? Object.fromEntries(keys.map(k=>[k,$('daily-field-'+k).value])) : null;
    if(fields && !attachments.length){
      options.headers['Content-Type']='application/json';
      options.body=JSON.stringify({...s,fields});
    }else{
      const form=new FormData();
      for(const [key,value] of Object.entries(s))form.append(key,value);
      if(fields){
        form.append('fields',JSON.stringify(fields));
      }else{
        const file=$('daily-file').files[0];
        if(!file)throw new Error('请选择日报文件');
        validateDailyFile(file);
        if(!dailyMarkdownExtensions.test(file.name) && file.size+attachments.reduce((total,attachment)=>total+attachment.size,0)>config.max_daily_attachment_bytes){
          throw new Error('日报原件和附件总大小超出限制');
        }
        form.append('file',file);
      }
      for(const attachment of attachments)form.append('attachments',attachment);
      options.body=form;
    }
    const snapshot = dailySnapshot();
    dailyBusy=true;dailyReady();
    ['daily-member','daily-date','daily-attachments','daily-file'].forEach(id=>{$(id).disabled=true;});
    dailyFeedback('正在保存日报和附件…');
    const result=await api('/api/daily/uploads',options);
    submittedDailySnapshot = snapshot;
    rememberSubmittedMember(s.member_id);
    const visibility=result.team_visible ? '团队可查看日报正文。' : '团队仅能查看提交状态。';
    dailyFeedback(`${result.duplicate?'该内容已提交，无需重复保存':'日报保存成功'}，${result.date} · ${result.attachment_count} 个附件。 ${visibility}`);
    if(result.week){
      const link=$('daily-team-link');
      link.href='#team?'+new URLSearchParams({week:result.week,member:result.member_id,date:result.date});
      link.hidden=false;
    }
  }catch(e){dailyFeedback(e.message,true);}
  finally{
    dailyBusy=false;
    ['daily-member','daily-date','daily-attachments','daily-file'].forEach(id=>{$(id).disabled=false;});
    dailyReady();
  }
};
function populateMembers(preferred){
  const remembered = lastSubmittedMember();
  for(const id of ['member','daily-member']){
    const selected=preferred || $(id).value || remembered;$(id).replaceChildren(new Option(config.members.length?'请选择报告所属成员':'请先在上方登记姓名',''));
    config.members.forEach(m=>$(id).add(new Option(m.name,m.id)));
    if(config.members.some(m=>m.id===selected))$(id).value=selected;
  }
  updateReady();dailyReady();
}
$('registration-form').onsubmit=async event=>{
  event.preventDefault();if(registrationBusy || !config)return;
  if(busy || dailyBusy){$('registration-feedback').textContent='请等待当前报告提交完成后再登记。';return;}
  const status=$('registration-feedback');status.classList.remove('error');
  try{
    registrationBusy=true;$('register-member').disabled=true;status.textContent='正在登记姓名…';
    const result=await api('/api/members',{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'ResearchWeekly'},body:JSON.stringify({name:$('registration-name').value})});
    config=await api('/api/public');populateMembers(result.member.id);$('registration-name').value='';feedback('');dailyFeedback('');
    status.textContent=`已登记 ${result.member.name}，已为你选好成员。请核对后提交日报或周报。`;
  }catch(e){status.textContent=e.message;status.classList.add('error');}
  finally{registrationBusy=false;$('register-member').disabled=false;}
};
async function initializePublic() {
    $('upload-endpoint').textContent='POST '+new URL('api/uploads',location.href).pathname;
    config = await api('/api/public');
    if (config.portal_url) {
      const portal = new URL(config.portal_url, location.href);
      if (['http:', 'https:'].includes(portal.protocol)) {
        $('registry-link').href = portal.href;
        portal.hash = 'research';
        $('research-link').href = portal.href;
      }
    }
    $('team-label').textContent = config.team_name;
    $('timezone-label').textContent = config.timezone;
    if (!$('week').value) $('week').value=config.week;
    if (!$('daily-date').value) $('daily-date').value=config.date;
    populateMembers();
    $('daily-upload-endpoint').textContent='POST '+new URL('api/daily/uploads',location.href).pathname;
    $('daily-file-hint').textContent=`支持 Markdown、TXT、CSV、Word、Excel、PowerPoint 和可选中文字的 PDF。Markdown 模板上限 ${Math.floor(config.max_report_bytes/1024)} KB。照片和扫描件可作为附件，再在线填写正文。`;
    $('daily-share-hint').textContent=config.daily_team_sharing
      ? '团队成员可以查看日报正文和标准周报的四个栏目。原件和附件保存在个人目录。'
      : '此入口仅展示日报提交状态。正文、原件和附件保存在个人目录。';
    $('daily-attachments').disabled=false;
    $('daily-attachment-hint').textContent=`最多 ${config.max_daily_attachments} 个，合计不超过 ${(config.max_daily_attachment_bytes/1024/1024).toLocaleString(undefined,{maximumFractionDigits:2})} MiB。附件原件保存在个人目录。`;
    $('file-hint').textContent=`单个文件上限 ${Math.floor(config.max_upload_bytes/1024/1024)} MiB。`;
    if(!config.members.length){$('registration-panel').querySelector('details').open = true;feedback('首次使用请在上方登记姓名。');dailyFeedback('首次使用请在上方登记姓名。');}
    updateReady();
}
$('session-resume').onclick = async () => {
  if (sessionRecoveryBusy || busy || dailyBusy || registrationBusy) return;
  sessionRecoveryBusy = true;
  $('session-resume').disabled = true;
  $('session-recovery-message').textContent = '正在确认登录状态…';
  try {
    await initializePublic();
    $('session-recovery').hidden = true;
    for (const id of ['upload-feedback', 'daily-feedback']) {
      if ($(id).textContent.includes(sessionExpiredMessage)) $(id).textContent = '';
    }
    toast('登录已恢复，可以继续编辑和提交。');
    await renderRoute();
  } catch (error) {
    $('session-recovery-message').textContent = error.code === 'feishu_login_required'
      ? sessionExpiredMessage : '暂时无法确认登录状态。' + error.message;
  } finally {
    sessionRecoveryBusy = false;
    $('session-resume').disabled = false;
  }
};
initializePublic().catch(error => {
  feedback('加载失败：' + error.message, true);
  dailyFeedback('加载失败：' + error.message, true);
  if (!config) $('member').replaceChildren(new Option('加载失败', ''));
});
renderRoute();
