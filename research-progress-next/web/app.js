'use strict';
const $ = id => document.getElementById(id);
const keys = ['done','results','blockers','next'];
let config, mode = 'form', busy = false, fileEpoch = 0, teamEpoch = 0, knowledgeEpoch = 0;
function feedback(message, error = false) {
  $('upload-feedback').textContent = message;
  $('upload-feedback').classList.toggle('error', error);
}
async function api(path, options = {}) {
  const r = await fetch(path.replace(/^\//, ''), {cache:'no-store', ...options});
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || `请求失败 (${r.status})`);
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
function markdown(root, text) {
  root.replaceChildren(); root.classList.add('markdown');
  let list;
  for (const line of text.split('\n')) {
    const h = /^(#{1,3}) (.*)$/.exec(line);
    let node;
    if (line.startsWith('- ')) {
      if (!list) {list = document.createElement('ul'); root.append(list);}
      node = document.createElement('li'); node.textContent = line.slice(2); list.append(node); continue;
    }
    list = null;
    if (!line.trim()) continue;
    node = document.createElement(h ? 'h'+h[1].length : 'p'); node.textContent = h ? h[2] : line; root.append(node);
  }
}
function selection() {
  if (!$('member').value || !$('week').value) throw new Error('请先选择成员与报告周次');
  return {member_id:$('member').value, week:$('week').value};
}
function updateReady() {
  $('submit-report').disabled = busy || !config || !$('member').value || !$('week').value;
}
function setMode(next) {
  if (busy) return;
  mode = next;
  $('fields-panel').hidden = mode !== 'form'; $('file-panel').hidden = mode !== 'file';
  keys.forEach(k => {$('field-'+k).disabled = mode !== 'form';});
  $('report-file').required = mode === 'file';
  $('mode-form').classList.toggle('active', mode === 'form'); $('mode-file').classList.toggle('active', mode === 'file');
  feedback('');
}
$('mode-form').onclick = () => setMode('form');
$('mode-file').onclick = () => setMode('file');
['member','week'].forEach(id => $(id).addEventListener('change', () => {feedback(''); updateReady();}));
$('download-template').onclick = async () => {
  try {const s=selection(); const t = await api('/api/report-template?'+new URLSearchParams(s)); download(t.filename, t.markdown);}
  catch(e) {feedback(e.message,true);}
};
$('report-file').onchange = async () => {
  const epoch = ++fileEpoch; $('file-preview').hidden = true; feedback('');
  const file = $('report-file').files[0]; if (!file) return;
  try {
    if (!/\.md$/i.test(file.name)) throw new Error('请选择 Markdown (.md) 文件');
    if (file.size > config.max_report_bytes) throw new Error('文件超出上传大小限制');
    const text = new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());
    if (epoch !== fileEpoch) return;
    $('file-preview').textContent=text; $('file-preview').hidden=false;
  } catch(e) {if(epoch===fileEpoch){$('report-file').value=''; feedback(e.message,true);}}
};
$('report-form').onsubmit = async event => {
  event.preventDefault(); if(busy) return;
  try {
    const s=selection(); const options={method:'POST',headers:{'X-Requested-With':'ResearchWeekly'}};
    if(mode==='form') {
      options.headers['Content-Type']='application/json';
      options.body=JSON.stringify({...s, fields:Object.fromEntries(keys.map(k=>[k,$('field-'+k).value]))});
    } else {
      const file=$('report-file').files[0]; if(!file) throw new Error('请选择周报文件');
      const form=new FormData(); form.append('member_id',s.member_id); form.append('week',s.week); form.append('file',file);
      options.body=form;
    }
    busy=true; updateReady(); $('member').disabled=true; $('week').disabled=true;
    feedback('正在校验成员目录与周报模板…');
    const result=await api('/api/uploads',options);
    feedback(`${result.duplicate ? '该内容已提交，无需重复保存' : '周报提交成功'}：${result.member_id} · ${result.week}。将参与该周团队汇总。`);
  } catch(e) {feedback(e.message,true);}
  finally {busy=false; $('member').disabled=false; $('week').disabled=false; updateReady();}
};
async function showTeam(week) {
  const epoch=++teamEpoch; $('team-reader').textContent='正在读取团队周报…';
  const doc=await api('/api/team/'+encodeURIComponent(week)); if(epoch!==teamEpoch)return;
  $('team-reader').replaceChildren();
  $('team-reader').append(button('下载 .md',()=>download(week+'.md',doc.markdown),'secondary download-document'));
  const body=document.createElement('div'); markdown(body,doc.markdown); $('team-reader').append(body);
}
async function loadTeam() {
  const data=await api('/api/team'); $('team-list').replaceChildren();
  data.items.forEach(row => $('team-list').append(button(`${row.week} · ${row.submitted}/${row.expected} 份 · 版本 ${row.revision}`,()=>showTeam(row.week))));
  if(data.items.length) await showTeam(data.items[0].week);
  else {$('team-reader').textContent='暂无团队总结。成员提交后，由维护人员或定时任务运行汇总 Skill。';}
}
async function loadKnowledge() {
  const data=await api('/api/knowledge'); $('knowledge-grid').replaceChildren();
  data.items.forEach(row => $('knowledge-grid').append(button(row.title,async()=>{
    const epoch=++knowledgeEpoch; const doc=await api('/api/knowledge/'+encodeURIComponent(row.name));
    if(epoch!==knowledgeEpoch)return; markdown($('knowledge-reader'),doc.content); $('knowledge-reader').hidden=false;
  },'knowledge-card')));
  if(!data.items.length) $('knowledge-grid').textContent='暂无知识文档，请由维护人员添加。';
}
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=async()=>{
  document.querySelectorAll('.view').forEach(v=>v.hidden=v.id!=='view-'+b.dataset.view);
  document.querySelectorAll('[data-view]').forEach(n=>n.classList.toggle('active',n===b));
  try {if(b.dataset.view==='team')await loadTeam(); if(b.dataset.view==='knowledge')await loadKnowledge();}
  catch(e){toast(e.message);}
});
$('refresh-team').onclick=()=>loadTeam().catch(e=>toast(e.message));
window.addEventListener('beforeunload', e=>{
  if(keys.some(k=>$('field-'+k).value.trim() || $('daily-field-'+k).value.trim()) || $('report-file').files.length || $('daily-file').files.length){e.preventDefault();e.returnValue='';}
});
let dailyMode='form', dailyBusy=false, dailyFileEpoch=0, registrationBusy=false;
function dailyFeedback(message,error=false){$('daily-feedback').textContent=message; $('daily-feedback').classList.toggle('error',error);}
function dailyReady(){$('daily-submit').disabled=dailyBusy || !config || !$('daily-member').value || !$('daily-date').value;}
function dailySelection(){
  if(!$('daily-member').value || !$('daily-date').value)throw new Error('请先选择成员与日报日期');
  return {member_id:$('daily-member').value,date:$('daily-date').value};
}
function setDailyMode(value){
  if(dailyBusy)return;
  dailyMode=value; $('daily-fields-panel').hidden=value!=='form'; $('daily-file-panel').hidden=value!=='file';
  keys.forEach(k=>{$('daily-field-'+k).disabled=value!=='form';}); $('daily-file').required=value==='file';
  $('daily-mode-form').classList.toggle('active',value==='form'); $('daily-mode-file').classList.toggle('active',value==='file'); dailyFeedback('');
}
$('daily-mode-form').onclick=()=>setDailyMode('form'); $('daily-mode-file').onclick=()=>setDailyMode('file');
['daily-member','daily-date'].forEach(id=>$(id).addEventListener('change',()=>{dailyFeedback('');dailyReady();}));
$('daily-download-template').onclick=async()=>{
  try{const t=await api('/api/daily-template?'+new URLSearchParams(dailySelection()));download(t.filename,t.markdown);}
  catch(e){dailyFeedback(e.message,true);}
};
$('daily-file').onchange=async()=>{
  const epoch=++dailyFileEpoch; $('daily-file-preview').hidden=true; dailyFeedback('');
  const file=$('daily-file').files[0]; if(!file)return;
  try{
    if(!/\.md$/i.test(file.name))throw new Error('请选择 Markdown (.md) 文件');
    if(!config || file.size>config.max_report_bytes)throw new Error('文件超出上传大小限制');
    const text=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer()); if(epoch!==dailyFileEpoch)return;
    $('daily-file-preview').textContent=text; $('daily-file-preview').hidden=false;
  }catch(e){if(epoch===dailyFileEpoch){$('daily-file').value='';dailyFeedback(e.message,true);}}
};
$('daily-form').onsubmit=async event=>{
  event.preventDefault(); if(dailyBusy)return;
  try{
    const s=dailySelection(),options={method:'POST',headers:{'X-Requested-With':'ResearchWeekly'}};
    if(dailyMode==='form'){
      options.headers['Content-Type']='application/json';options.body=JSON.stringify({...s,fields:Object.fromEntries(keys.map(k=>[k,$('daily-field-'+k).value]))});
    }else{
      const file=$('daily-file').files[0];if(!file)throw new Error('请选择日报文件');
      const form=new FormData();form.append('member_id',s.member_id);form.append('date',s.date);form.append('file',file);options.body=form;
    }
    dailyBusy=true;dailyReady();$('daily-member').disabled=true;$('daily-date').disabled=true;dailyFeedback('正在校验成员与日报模板…');
    const result=await api('/api/daily/uploads',options);
    dailyFeedback(`${result.duplicate?'该内容已提交，无需重复保存':'日报提交成功'}：${result.member_id} · ${result.date}。已单独保存，请另行整理和提交周报。`);
  }catch(e){dailyFeedback(e.message,true);}
  finally{dailyBusy=false;$('daily-member').disabled=false;$('daily-date').disabled=false;dailyReady();}
};
function populateMembers(preferred){
  for(const id of ['member','daily-member']){
    const selected=preferred || $(id).value;$(id).replaceChildren(new Option(config.members.length?'请选择报告所属成员':'请先在上方登记姓名',''));
    config.members.forEach(m=>$(id).add(new Option(`${m.name}（${m.id}）`,m.id)));
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
(async()=>{
  try {
    $('upload-endpoint').textContent='POST '+new URL('api/uploads',location.href).pathname; config=await api('/api/public'); if(config.portal_url){$('registry-link').href=config.portal_url; $('registry-link').hidden=false;} $('team-label').textContent=config.team_name; $('timezone-label').textContent=config.timezone;
    $('week').value=config.week; $('daily-date').value=config.date; populateMembers();
    $('daily-upload-endpoint').textContent='POST '+new URL('api/daily/uploads',location.href).pathname;
    $('daily-file-hint').textContent=`UTF-8 Markdown，上限 ${Math.floor(config.max_report_bytes/1024)} KB。文件标题的成员和日期必须与当前选择一致。`;
    $('file-hint').textContent=`UTF-8 Markdown，上限 ${Math.floor(config.max_report_bytes/1024)} KB。文件标题的成员和周次必须与当前选择一致。`;
    if(!config.members.length){feedback('首次使用请在上方登记姓名。');dailyFeedback('首次使用请在上方登记姓名。');}
    updateReady();
    const target=location.hash.slice(1);if(['daily','upload','team','knowledge'].includes(target))document.querySelector('[data-view="'+target+'"]').click();
  } catch(e){feedback('加载失败：'+e.message,true);dailyFeedback('加载失败：'+e.message,true); $('member').replaceChildren(new Option('加载失败',''));}
})();
