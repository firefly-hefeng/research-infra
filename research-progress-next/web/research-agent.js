(() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const labels = {running:'运行中',completed:'已完成',partial:'部分完成',unavailable:'资料暂不可用',no_protocol:'暂无匹配实验',failed:'运行失败',interrupted:'已中断'};
  const base = 'api/research-experiments';
  let generation = 0;
  const element = (tag, value, parent, cls) => {
    const node = document.createElement(tag);
    if (value != null) node.textContent = value;
    if (cls) node.className = cls;
    parent.append(node);
    return node;
  };
  function link(parent, title, url, external=false) {
    if (!url) return element('span',title,parent);
    let target;try {target=new URL(url,location.href);} catch {return element('span',title,parent);}
    if (target.origin !== location.origin && (!external || target.protocol !== 'https:' || target.username || target.password)) return element('span',title,parent);
    const a = element('a',title,parent); a.href = target.href;
    if(target.origin!==location.origin){a.target='_blank';a.rel='noopener noreferrer';}
    return a;
  }
  function reportLink(row) {
    if(row.original_url)return row.original_url;
    const match=/^(daily|weekly):([a-z][a-z0-9_-]{1,31}):(\d{4}-(?:W\d{2}|\d{2}-\d{2}))$/.exec(row.id||'');
    return match ? '/progress/api/report-source/'+match.slice(1).join('/') : null;
  }
  function list(parent, items) {
    if (!items?.length) return;
    const ul = element('ul',null,parent);
    for (const text of items) element('li',text,ul);
  }
  function details(parent, title) {
    const block = element('details',null,parent); element('summary',title,block); return block;
  }
  function chart(parent, title, rows, max, suffix) {
    if (!window.d3 || !(max > 0) || rows.some(([,v])=>!Number.isFinite(v))) return;
    const fig=element('figure',null,parent); element('figcaption',title,fig);
    const svg=d3.select(fig).append('svg').attr('class','bars').attr('viewBox','0 0 370 '+(rows.length*32+8)).attr('role','img').attr('aria-label',rows.map(([k,v])=>k+' '+v+suffix).join('，'));
    const scale=d3.scaleLinear().domain([0,max]).range([0,173]);
    rows.forEach(([k,v],i)=>{const y=i*32+17; svg.append('text').attr('x',0).attr('y',y+4).attr('font-size',14).text(k);
      svg.append('rect').attr('class','track').attr('x',117).attr('y',y-7).attr('width',173).attr('height',10);
      svg.append('rect').attr('x',117).attr('y',y-7).attr('width',scale(v)).attr('height',10);
      svg.append('text').attr('x',300).attr('y',y+4).attr('font-size',14).text(v+suffix);});
  }
  function render(record) {
    const root=$('#record');root.replaceChildren();root.hidden=false;
    element('p',labels[record.status] || record.status,root,'kicker');
    element('h2',record.plan?.direction.title || record.query,root);
    element('p',new Date(record.started_at).toLocaleString('zh-CN'),root,'meta');
    if(record.message) element('p',record.message,root);
    if(record.missing_sources?.length) element('p','本次未取得：'+record.missing_sources.map(x=>({papers:'文献目录',research:'研究档案',library:'资料台账'})[x]||x).join('、'),root);
    const plan=record.plan;
    if(plan){
      if(plan.direction.question) element('p',plan.direction.question,root);
      const c=plan.context, basis=details(root,'研究基础与候选资料');
      for(const row of c.archive||[]) {element('strong',row.name,basis);element('p',row.summary,basis);}
      for(const [key,title] of [['dataset','数据'],['model','模型'],['papers','文献']]) {
        const group=c[key];element('h3',title+'候选 · '+(group?.total??0),basis);
        if(group?.items?.length){const ul=element('ul',null,basis);
          for(const row of group.items){const dest=key==='papers'?'/papers/#graph?node='+encodeURIComponent(row.id):row.source_url;
            link(element('li',null,ul),row.title,dest,true);}}
      }
      if(c.reports?.length){element('h3','方向关联报告',basis);for(const row of c.reports) link(element('p',null,basis),row.title||row.id,reportLink(row));}
      list(root,plan.gaps);
    }
    for(const r of record.experiment?.results||[]) {
      const block=element('section',null,root,'result');element('h3',r.title,block);
      element('p',r.question,block,'instrument'); list(block,r.observations);
      const m=r.metrics||{};
      if(m.retained_frame_pct)chart(block,'两种门限下的帧保留率',[['−50 dBFS',m.retained_frame_pct['-50']],['−40 dBFS',m.retained_frame_pct['-40']]],100,'%');
      if(m.expanded_matches)chart(block,'同一批题录中的候选数',[['仅题名',m.title_matches],['题名与元数据',m.expanded_matches]],m.expanded_matches,' 条');
      if(r.matched_records?.length){
        const items=details(block,'查看命中的文献 · '+r.matched_records.length);
        const ul=element('ul',null,items);
        for(const p of r.matched_records){const li=element('li',null,ul);link(li,p.title,'/papers/#graph?node='+encodeURIComponent(p.id));}
      }
      const method=details(block,'方法与适用范围');element('p',r.method,method);list(method,r.limitations);
      for(const src of r.sources||[]) {const p=element('p',null,method);link(p,src.title||src.id,src.url,true);
        if(src.credit||src.license)element('span',' · '+[src.credit,src.license].filter(Boolean).join(' · '),p,'meta');}
      if(r.next)element('p','下一步：'+r.next,block);
    }
    const foot=element('div',null,root,'footer-links');link(foot,'实验原始记录（JSON）',base+'/'+record.id);link(foot,'查看方向文献图谱','/papers/#graph');
  }
  async function json(url, options) {
    const res=await fetch(url,{cache:'no-store',...options});
    if(!res.headers.get('Content-Type')?.includes('application/json'))throw Error('请从科研工作台重新登录后打开。');
    const body=await res.json();
    if(!res.ok)throw Error(body.error||'读取失败，请重试。');return body;
  }
  async function historyList() {
    try{const {items}=await json(base);const ul=$('#history');ul.replaceChildren();$('#empty').textContent=items.length?'':'尚无实验记录。';
      for(const r of items){const li=element('li',null,ul);link(li,r.title||r.query,'#'+r.id);element('small',labels[r.status]+' · '+new Date(r.started_at).toLocaleDateString('zh-CN'),li);}
    }catch(err){$('#empty').textContent=err.message;}
  }
  async function watch() {
    const id=location.hash.slice(1), token=++generation;$('#run').disabled=false;
    if(!/^[0-9a-f]{32}$/.test(id)){$('#record').hidden=true;$('#status').textContent='';return;}
    try{for(;;){const row=await json(base+'/'+id);if(token!==generation)return;
      render(row);$('#run').disabled=row.status==='running';$('#status').textContent=row.status==='running'?'正在读取团队资料并运行实验…':'';
      if(row.status!=='running'){historyList();break;}await new Promise(done=>setTimeout(done,2000));}
    }catch(err){if(token===generation){$('#run').disabled=false;$('#status').textContent=err.message;}}
  }
  $('#form').addEventListener('submit',async ev=>{
    ev.preventDefault();const query=$('#direction').value.trim();if(!query)return;
    $('#run').disabled=true;$('#status').textContent='正在创建实验记录…';
    try{const row=await json(base,{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'ResearchWeekly'},
      body:JSON.stringify({query,request_id:crypto.randomUUID().replaceAll('-','')})});location.hash=row.id;historyList();}
    catch(err){$('#status').textContent=err.message;$('#run').disabled=false;}
  });
  async function suggestDirections() {
    try {
      const {items}=await json('api/directions');
      for(const row of items||[]) if(row.title) element('option',null,$('#team-directions')).value=row.title;
    } catch { /* Manual direction entry also works when the directory is unavailable. */ }
  }
  window.addEventListener('hashchange',watch);suggestDirections();historyList();watch();
})();
