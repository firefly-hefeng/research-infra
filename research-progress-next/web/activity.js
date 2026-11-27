'use strict';

const teamActivity = (() => {
  const $ = id => document.getElementById(id);
  const labels = {published:'已汇总',ready:'已收到',queued:'待整理',processing:'整理中',needs_review:'待复核',failed:'整理暂未完成',missing:'未收到'};
  const dailyFields = {done:'今日完成',results:'结果与证据',blockers:'问题与阻塞',next:'明日计划'};
  const weeklyFields = {...dailyFields,done:'本周完成',next:'下周计划'};
  const scopes = {weekly:{state:null,filter:{week:'',member:''},epoch:0,snapshot:null,details:new Map()},daily:{state:null,filter:{week:'',member:'',date:''},epoch:0,snapshot:null,details:new Map()}};
  let active = false, timer, directionEpoch = 0, directionSnapshot, archive = [], focusKind = null;

  function hash(query) { return '#team' + (query.size ? '?' + query : ''); }
  function currentQuery() {
    const query = new URLSearchParams();
    const weekly = scopes.weekly, daily = scopes.daily;
    const weeklyWeek=weekly.filter.week||weekly.state?.current_week||daily.state?.current_week||weekly.state?.week;
    const dailyWeek=daily.filter.week||daily.state?.current_week||weekly.state?.current_week||daily.state?.week;
    if (weeklyWeek) query.set('week',weeklyWeek);
    if (weekly.filter.member) query.set('member',weekly.filter.member);
    if (dailyWeek) query.set('daily_week',dailyWeek);
    query.set('daily_member',daily.filter.member);
    return query;
  }
  function weekRoute(week, member = scopes.weekly.filter.member, detail = false) {
    const query = currentQuery();
    if (week) query.set('week',week); else query.delete('week');
    if (member) query.set('member',member); else query.delete('member');
    if (detail) query.set('report','weekly');
    return hash(query);
  }
  function dailyRoute(week, member = scopes.daily.filter.member, date) {
    const query = currentQuery();
    if (week) query.set('daily_week',week);
    query.set('daily_member',member || '');
    if (date) query.set('date',date);
    return hash(query);
  }
  function adjacent(kind, offset) {
    const state = scopes[kind].state;
    if (!state) return;
    const thursday = new Date(state.dates[3]+'T00:00:00Z');
    thursday.setUTCDate(thursday.getUTCDate()+offset*7);
    const year = thursday.getUTCFullYear();
    const week = Math.ceil((thursday-new Date(Date.UTC(year,0,1))+86400000)/604800000);
    const value = `${year}-W${String(week).padStart(2,'0')}`;
    location.hash = kind === 'weekly' ? weekRoute(value) : dailyRoute(value);
  }
  function safeDownload(value) {
    try {
      const url = new URL(value,location.href);
      if (url.origin !== location.origin || !/^\/(?:progress\/)?api\/report-source\//.test(url.pathname)) return null;
      return 'api/report-source/'+url.pathname.split('/api/report-source/')[1]+url.search;
    } catch { return null; }
  }
  function nameOf(record,state) { return record.member_name || record.name || state.members.find(person=>person.id===record.member_id)?.name || '成员'; }
  function recordKey(record,kind) { return kind+':'+record.member_id+':'+(kind==='daily'?record.date:record.week); }
  function snapshotUI(root) {
    const entries = new Map([...root.querySelectorAll('details[data-report-key]')].map(item=>[item.dataset.reportKey,item.open]));
    const activeElement = root.contains(document.activeElement) ? document.activeElement : null;
    const focus = activeElement ? {key:activeElement.closest('[data-report-key]')?.dataset.reportKey,summary:activeElement.tagName==='SUMMARY',href:activeElement.getAttribute('href')} : null;
    return {entries,focus};
  }
  function restoreFocus(root,focus) {
    if (!focus) return;
    const scope = [...root.querySelectorAll('[data-report-key]')].find(item=>item.dataset.reportKey===focus.key);
    const target = focus.summary ? scope?.querySelector('summary') : [...(scope||root).querySelectorAll('a')].find(link=>link.getAttribute('href')===focus.href);
    target?.focus({preventScroll:true});
  }
  function downloads(record) {
    const group = node('div',undefined,'report-downloads');
    const candidates = [{url:record.original_url||record.download?.url,label:record.original_label||record.download?.label||'下载原始记录'},
      ...(record.attachments||record.download?.attachments||[]).map(item=>({url:item.url,label:'附件 · '+item.name}))];
    const seen = new Set();
    for (const candidate of candidates) {
      const href = safeDownload(candidate.url);
      if (!href || seen.has(href)) continue;
      seen.add(href);
      const link = node('a',candidate.label,'text-link');
      link.href=href;
      link.setAttribute('download','');
      group.append(link);
    }
    return group;
  }
  function reportBody(record,kind,state) {
    const body = node('div',undefined,'report-entry-body');
    if (record.fields) {
      const fields = node('dl',undefined,'report-summary-list');
      for (const [key,label] of Object.entries(kind==='daily'?dailyFields:weeklyFields)) {
        const group = node('div'), value = node('dd');
        const text = Array.isArray(record.fields[key]) ? record.fields[key].join('\n') : record.fields[key];
        if (typeof text==='string' && text.trim()) markdown(value,presentReportText(text));
        else value.append(node('p','原记录未填写此项。','muted'));
        group.append(node('dt',label),value);
        fields.append(group);
      }
      body.append(fields);
    } else {
      const text = record.content_deferred ? '此条记录已归档，正文可按需读取。'
        : record.shared===false ? '已收到记录，此入口尚未共享正文。'
          : record.unavailable ? '已保留提交记录，正文暂不可读。' : '已收到记录，正文暂未整理为可读栏目。';
      body.append(node('p',text,'muted'));
      if (record.content_deferred) {
        const link = node('a','阅读全文 ↗','text-link');
        link.href = kind==='daily' ? dailyRoute(state.week,record.member_id,record.date) : weekRoute(state.week,record.member_id,true);
        body.append(link);
      }
    }
    const files = downloads(record);
    if (files.childElementCount) body.append(files);
    else if (record.attachment_count) body.append(node('p',`${record.attachment_count} 个附件已归档，下载入口暂不可读。`,'muted'));
    return body;
  }
  function readablePreview(record) {
    const text = Object.keys(dailyFields).map(key=>record.fields?.[key]).find(value=>typeof value==='string'&&value.trim());
    if (!text) return record.content_deferred ? '已提交，阅读全文可按需读取正文。' : record.fields ? '已提交研究记录。' : '已提交记录，展开查看读取情况与原件。';
    return firstParagraph(text);
  }
  function firstParagraph(text) {
    return presentReportText(text).split(/\n\s*\n/)[0].replace(/\[([^\]]+)\]\([^)]+\)/g,'$1').replace(/^\s*#+\s*/gm,'').replace(/\s+/g,' ').trim();
  }
  function presentReportText(text) {
    // Only an entire, consecutive list beginning at 1 is reformatted. URL paths,
    // decimal values and ordinary sample counts do not satisfy these boundaries.
    return text.trim().split(/\n\s*\n/).flatMap(paragraph=>{
      const prefix=/^(?:本周完成|今日完成|结果与证据|问题与阻塞|下周计划|明日计划)\s*[:：]\s*/.exec(paragraph)?.[0]||'';
      const content=paragraph.slice(prefix.length);
      const items=[...content.matchAll(/(^|\s+|[。；！？])([1-9]\d*)[)）]/g)];
      if(items.length<2||items[0].index!==0||items.some((item,index)=>Number(item[2])!==index+1))return [paragraph];
      const starts=items.map(item=>item.index+item[1].length);
      return starts.map((start,index)=>(index===0?prefix:'')+content.slice(start,starts[index+1]??content.length).trim());
    }).join('\n\n');
  }
  function recordsFor(kind,state) {
    let records = state[kind==='daily'?'daily_records':'weekly_reports'];
    if (!Array.isArray(records)) {
      records = state.members.flatMap(person=>kind==='daily'
        ? person.days.map(date=>({member_id:person.id,member_name:person.name,date,fields:null,content_deferred:true}))
        : person.weekly_status!=='missing' ? [{member_id:person.id,member_name:person.name,week:state.week,status:person.weekly_status,fields:null,content_deferred:true}] : []);
    }
    const scope=scopes[kind], filter=scope.filter;
    records = records.filter(record=>!filter.member||record.member_id===filter.member).map(record=>({...record}));
    const selected = kind==='daily' ? state.selected_daily : state.selected_weekly;
    const match = records.find(record=>record.member_id===filter.member&&(kind==='weekly'||record.date===filter.date));
    if (match && selected?.fields && filter.member) Object.assign(match,selected);
    for(const record of records) {
      const key=recordKey(record,kind);
      if(record.fields) scope.details.set(key,record.fields);
      else if(record.content_deferred&&!record.unavailable&&record.shared!==false&&scope.details.has(key)) record.fields=scope.details.get(key);
    }
    return records.sort((a,b)=>(b.date||b.week||'').localeCompare(a.date||a.week||'')||nameOf(a,state).localeCompare(nameOf(b,state),'zh-CN'));
  }
  function renderFeed(kind,state) {
    const root = $(kind==='daily'?'daily-feed':'activity-weekly-list');
    const ui = snapshotUI(root), filter = scopes[kind].filter;
    const records = recordsFor(kind,state);
    root.replaceChildren();
    records.forEach((record,index)=>{
      const card = node('details',undefined,'report-entry report-entry-'+kind), key=recordKey(record,kind);
      card.dataset.reportKey=key;card.dataset.member=record.member_id;card.dataset.period=kind==='daily'?record.date:record.week;
      const chosen = !!filter.member && record.member_id===filter.member && focusKind===kind && (kind==='weekly'||record.date===filter.date);
      card.open = chosen || (ui.entries.has(key)?ui.entries.get(key):kind==='daily'&&index===0);
      if(kind==='daily'&&record.date===filter.date) card.dataset.selectedDate='true';
      const heading=node('summary'), title=node('span',undefined,'report-entry-title');
      title.append(node('strong',nameOf(record,state)),node('span',kind==='daily'?record.date:record.week,'record-date'));
      heading.append(title,node('small',kind==='weekly'?'周报原文':'日报原文','record-source'),node('span',readablePreview(record),'report-entry-preview'));
      heading.append(node('span','展开阅读全文与原件','report-expand-hint'));
      heading.append(node('span','收起正文','report-collapse-hint'));
      card.append(heading,reportBody(record,kind,state));root.append(card);
    });
    if(!records.length) {
      const empty=node('div',undefined,'report-feed-empty');
      const qualifier=filter.member?'该成员在此周':'本周';
      empty.append(node('h3',kind==='daily'?qualifier+'尚无日报记录':qualifier+'尚未收到周报'),node('p',kind==='daily'?'可切换日报周次或成员查看历史记录。':'已发布的阶段汇总可从下方归档查阅。','muted'));
      root.append(empty);if(kind==='weekly') renderLatestWeek(empty,state.week);
    }
    const legacyReader=$(kind==='daily'?'activity-report':'activity-weekly-report');
    legacyReader.hidden=true;legacyReader.replaceChildren();
    const selected=kind==='daily'?state.selected_daily:state.selected_weekly;
    const matching=records.find(record=>record.member_id===filter.member&&(kind==='weekly'||record.date===filter.date));
    if(selected?.fields&&filter.member&&!matching) {
      legacyReader.hidden=false;
      legacyReader.append(node('h3',`${state.members.find(person=>person.id===filter.member)?.name||'成员'} · ${kind==='daily'?filter.date:state.week} ${kind==='daily'?'日报':'周报'}`),reportBody({...selected,member_id:filter.member},kind,state));
    }
    restoreFocus(root,ui.focus);
    if(focusKind===kind) {
      const target=[...root.querySelectorAll('[data-report-key]')].find(card=>card.dataset.member===filter.member&&(kind==='weekly'||card.dataset.period===filter.date))||(!legacyReader.hidden?legacyReader:root);
      focusKind=null;if(target.tagName==='DETAILS')target.open=true;
      const focus=target.tagName==='DETAILS'?target.querySelector('summary'):target;
      if(focus.tagName!=='SUMMARY')focus.tabIndex=-1;
      focus.focus({preventScroll:true});target.scrollIntoView({block:'start'});
    }
  }
  function renderLatestWeek(root,week) {
    const latest=archive[0];if(!latest)return;
    const link=node('a',`阅读团队最近已发布周报 · ${latest.week} ↗`,'text-link');link.href=weekRoute(latest.week,'');
    link.addEventListener('click',()=>{$('weekly-archive').open=true;});root.append(link);
  }
  function renderTimetable(kind,state) {
    const people=state.members.filter(person=>!scopes[kind].filter.member||scopes[kind].filter.member===person.id);
    const root=$(kind==='weekly'?'weekly-timetable':'activity-grid'),chosen=scopes.daily.filter.date;
    const focused=root.contains(document.activeElement)?document.activeElement.getAttribute('href'):null;root.replaceChildren();
    const weekly=state.weekly_timetable;
    const weeks=weekly?.weeks||[state.week];
    const records=weekly?.records||recordsFor('weekly',state).map(record=>({...record,readable:!!record.fields||!!record.original_url}));
    people.forEach(person=>{
      const row=node('article',undefined,'activity-member-row'),header=node('header');
      row.dataset.member=person.id;header.append(node('h3',person.name));row.append(header);
      const days=node('div',undefined,kind==='weekly'?'activity-days activity-weeks':'activity-days');
      (kind==='weekly'?weeks:state.dates).forEach((date,index)=>{
        const record=kind==='weekly'?records.find(record=>record.member_id===person.id&&record.week===date):null;
        const exists=kind==='weekly'?!!record:person.days.includes(date);
        const readable=kind==='daily'?exists:exists&&record.readable!==false;
        const mark=node(readable?'a':'span',undefined,'activity-day');mark.dataset.period=date;
        if(kind==='weekly')mark.append(node('span',date.slice(0,4)),node('strong',date.slice(5)));
        else mark.append(node('span','周'+['一','二','三','四','五','六','日'][index]),node('strong',date.slice(5)));
        const type=kind==='weekly'?'周报':'日报';
        mark.setAttribute('aria-label',`${person.name} ${date} ${type}${readable?'，阅读原文':exists?'，原文暂不可读':'，暂无归档记录'}`);
        if(!readable)mark.append(node('span',exists?'原文暂不可读':'暂无归档记录','report-sr-only'));
        if(kind==='daily'&&chosen===date)mark.dataset.selectedDate='true';
        if(kind==='weekly'&&scopes.weekly.filter.member===person.id&&state.week===date)mark.dataset.selectedDate='true';
        if(readable&&mark.dataset.selectedDate)mark.setAttribute('aria-current',kind==='daily'?'date':'true');
        if(readable) {
          mark.href=kind==='weekly'?weekRoute(date,person.id,true):dailyRoute(state.week,person.id,date);
          mark.addEventListener('click',event=>{if(location.hash===mark.getAttribute('href')){event.preventDefault();focusKind=kind;renderFeed(kind,state);}});
        }
        days.append(mark);
      });row.append(days);root.append(row);
    });
    if(focused)[...root.querySelectorAll('a')].find(link=>link.getAttribute('href')===focused)?.focus({preventScroll:true});
  }
  function renderScope(kind,state) {
    const prefix=kind==='weekly'?'activity':'daily',filter=scopes[kind].filter;
    const picker=$(kind==='weekly'?'activity-member':'daily-member-filter');
    picker.replaceChildren(new Option('全部成员',''),...state.members.map(person=>new Option(person.name,person.id)));
    picker.value=state.members.some(person=>person.id===filter.member)?filter.member:'';
    const all=$(kind==='weekly'?'weekly-all-members':'daily-all-members');
    all.hidden=!filter.member;
    all.href=kind==='weekly'?weekRoute(state.week,''):dailyRoute(state.week,'');
    $(prefix+'-week').textContent=`${state.week} · ${state.dates[0]} 至 ${state.dates[6]}`;
    $(prefix+'-next').disabled=state.week>=state.current_week;$(prefix+'-current').disabled=state.week===state.current_week;
    $(kind==='weekly'?'activity-weekly-status':'activity-status').textContent='';
    renderFeed(kind,state);renderTimetable(kind,state);
  }
  async function refreshScope(kind,loadArchive=true) {
    if(!active)return;
    const scope=scopes[kind],request=++scope.epoch,query=new URLSearchParams();
    if(scope.filter.week)query.set('week',scope.filter.week);if(scope.filter.member)query.set('member',scope.filter.member);
    if(kind==='daily'&&scope.filter.date)query.set('date',scope.filter.date);if(kind==='weekly'&&focusKind==='weekly')query.set('report','weekly');
    try {
      const result=await api('/api/team/activity?'+query);if(!active||request!==scope.epoch)return;
      const changed=scope.state&&(scope.state.week!==result.week||scope.state.weekly_revision!==result.weekly_revision);scope.state=result;
      const fingerprint=JSON.stringify({filter:scope.filter,linkContext:currentQuery().toString(),result}),status=$(kind==='weekly'?'activity-weekly-status':'activity-status');
      if(fingerprint!==scope.snapshot||focusKind===kind||status.dataset.error) {scope.snapshot=fingerprint;delete status.dataset.error;renderScope(kind,result);}
      if(kind==='weekly'&&changed&&loadArchive)await loadTeam(result.week);return result;
    } catch(error) {
      if(!active||request!==scope.epoch)return;const status=$(kind==='weekly'?'activity-weekly-status':'activity-status');
      status.dataset.error='true';status.textContent='暂时无法更新，保留已读取的记录。稍后会自动重试。';
    }
  }
  async function refreshDirections() {
    const request=++directionEpoch,payload=await api('/api/directions').catch(()=>null);if(!active||request!==directionEpoch)return;
    if(!payload){if(!directionSnapshot)$('activity-direction-list').replaceChildren(node('p','研究方向暂未读取成功。','muted'));return;}
    const fingerprint=JSON.stringify(payload);if(fingerprint===directionSnapshot)return;directionSnapshot=fingerprint;
    const entries=(payload.items||[]).map(direction=>{const article=node('article',undefined,'activity-direction'),link=node('a',direction.title);link.href='#directions?'+new URLSearchParams({item:direction.id});article.append(link,node('small',direction.updated_at?`核对于 ${direction.updated_at}`:'核对日期待补充','muted'));return article;});
    $('activity-direction-list').replaceChildren(...(entries.length?entries:[node('p','暂无可读的方向记录。','muted')]));
  }
  function stop(){active=false;scopes.weekly.epoch++;scopes.daily.epoch++;directionEpoch++;clearInterval(timer);progressDigest.stop();}
  function open(query) {
    stop();active=true;const legacyDaily=query.has('date')&&!query.has('daily_week'),previousDaily=scopes.daily.filter;
    scopes.weekly.filter={week:legacyDaily?(scopes.weekly.state?.week||scopes.weekly.filter.week):query.get('week')||'',member:legacyDaily?scopes.weekly.filter.member:query.get('member')||''};
    scopes.daily.filter={week:query.get('daily_week')||(legacyDaily?query.get('week'):'')||scopes.daily.state?.week||'',
      member:query.has('daily_member')?query.get('daily_member'):legacyDaily?query.get('member')||'':previousDaily.member,date:query.get('date')||''};
    focusKind=query.get('report')==='weekly'?'weekly':query.has('date')?'daily':null;
    if(query.has('date'))$('activity-records').open=true;
    if(query.get('report')==='weekly')$('weekly-archive').open=false;
    refreshScope('daily');refreshDirections();progressDigest.start();
    timer=setInterval(()=>{if(!document.hidden)refreshAll();},30000);return refreshScope('weekly',false);
  }
  function refreshAll(){return Promise.all([refreshScope('weekly'),refreshScope('daily'),refreshDirections(),progressDigest.refresh()]);}
  for(const kind of ['weekly','daily']) {
    const prefix=kind==='weekly'?'activity':'daily';$(prefix+'-prev').onclick=()=>adjacent(kind,-1);$(prefix+'-next').onclick=()=>adjacent(kind,1);
    $(prefix+'-current').onclick=()=>{const state=scopes[kind].state;if(state)location.hash=kind==='weekly'?weekRoute(state.current_week):dailyRoute(state.current_week);};
    $(kind==='weekly'?'activity-member':'daily-member-filter').onchange=event=>{const state=scopes[kind].state;if(state)location.hash=kind==='weekly'?weekRoute(state.week,event.target.value):dailyRoute(state.week,event.target.value);};
  }
  document.addEventListener('visibilitychange',()=>{if(active&&!document.hidden)refreshAll();});
  return {open,stop,refresh:refreshAll,week:()=>scopes.weekly.state?.week,weeklyMember:()=>scopes.weekly.filter.member,weekRoute,
    setArchive(items){archive=items||[];if(scopes.weekly.state&&!recordsFor('weekly',scopes.weekly.state).length)renderFeed('weekly',scopes.weekly.state);}};
})();
