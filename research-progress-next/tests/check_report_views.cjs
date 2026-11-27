/* Reproduce independent reading filters with synthetic reports; no model or report writes. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const {chromium} = require(process.env.RESEARCH_PLAYWRIGHT_MODULE || 'playwright');
const web = path.resolve(__dirname,'../web');
const roster = [{id:'he',name:'何锋'},{id:'lu',name:'陆梓健'},{id:'empty-a',name:'未提交甲'},{id:'empty-b',name:'未提交乙'}];
const fields = {done:'合成日报：升级数据分类和科研协同规则',results:'合成结果：整理科研平台说明',blockers:'合成阻塞：实验对照条件待核对',next:'合成计划：复查数据与实验接口'};
const weeklyFirstItem='本周完成：1）合成周报：验证声音研究基线。';
const weeklyFields = {...fields,done:weeklyFirstItem+'2）整理实验条件。3）核对评估结果。4）保留全部原始证据。',
  results:'样本 240 例，均值 1.23，参考 https://example.test/data/1)sample/2)condition?ratio=1.25',
  blockers:'问题与阻塞:1) 先核对设备 2) 再核对条件',next:'合成周报：下一周检验跨设备适用性'};
const sourceRoot = '/progress/api/report-source/daily/he/2026-11-14';
let revision = 1, failDaily = false, deferred = false, stress = false, slowWeekly = false, slowDaily = false;
const longURL='https://example.test/evidence/'+ 'unbrokensegment'.repeat(24);
const longFilename='StudyEvidenceWithoutAnySpaces'.repeat(12)+'.pdf';
const methods = [];
function dates(week) {
  const monday = new Date('2026-11-09T00:00:00Z');
  monday.setUTCDate(monday.getUTCDate()+(Number(week.slice(-2))-46)*7);
  return Array.from({length:7},(_,index)=>{const day=new Date(monday);day.setUTCDate(day.getUTCDate()+index);return day.toISOString().slice(0,10);});
}
const server=http.createServer((request,response)=>{
  methods.push(request.method);
  const url=new URL(request.url,'http://127.0.0.1');
  const json=(data,status=200)=>{response.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});response.end(JSON.stringify(data));};
  if(url.pathname==='/progress/api/public')return json({team_name:'独立报告视图合成测试',members:roster,week:'2026-W46',date:'2026-11-14',timezone:'Asia/Shanghai',max_upload_bytes:20971520,max_report_bytes:65536,daily_team_sharing:true,max_daily_attachments:8,max_daily_attachment_bytes:20971520});
  if(url.pathname==='/progress/api/progress-digest')return json({document:null,status:{state:'disabled'}});
  if(url.pathname==='/progress/api/directions')return json({items:[],unavailable:[]});
  if(url.pathname==='/progress/api/team')return json({items:['2026-W45','2026-W44'].map(week=>({week,submitted:1,expected:4}))});
  if(/^\/progress\/api\/team\/2026-W(?:44|45)$/.test(url.pathname))return json({week:url.pathname.split('/').pop(),members:[],overview:['已归档阶段成果'],team_risks:[],next_actions:[]});
  if(url.pathname==='/progress/api/team/activity') {
    const week=url.searchParams.get('week')||'2026-W46', member=url.searchParams.get('member');
    if(failDaily&&week==='2026-W46')return json({error:'synthetic temporary failure'},503);
    const reportFields=stress?{...fields,done:'完整首段'+ '长文本'.repeat(120)+'首段结束\n\n第二段完整正文结束',results:longURL}:fields;
    const weeklyReportFields=stress?{...weeklyFields,results:longURL,blockers:'UnbrokenResearchConstraint'.repeat(20)}:weeklyFields;
    const dailyRecord={member_id:'he',member_name:'何锋',date:'2026-11-14',week:'2026-W46',fields:deferred?null:reportFields,content_deferred:deferred,url:'/progress/#team?week=2026-W46&member=he&date=2026-11-14',original_url:sourceRoot,original_label:'下载日报记录 Markdown',attachment_count:2,attachments:[{name:'evidence.txt',url:sourceRoot+'/1'},{name:stress?longFilename:'results.pdf',url:sourceRoot+'/2'}]};
    const weeklyRecord={member_id:'lu',member_name:'陆梓健',week,status:'ready',fields:weeklyReportFields,url:'/progress/#team?week='+week+'&member=lu&report=weekly',original_url:'/progress/api/report-source/weekly/lu/'+week,original_label:'下载周报原件',attachments:[]};
    const weeks=Array.from({length:4},(_,index)=>'2026-W'+String(Number(week.slice(-2))-index).padStart(2,'0'));
    const payload={week,current_week:'2026-W46',dates:dates(week),weekly_revision:'synthetic',source_revision:revision,
      members:roster.map(person=>({...person,days:week==='2026-W46'&&person.id==='he'?['2026-11-14']:[],weekly_status:week!=='2026-W46'&&person.id==='lu'?'ready':'missing',weekly_readable:week!=='2026-W46'&&person.id==='lu'})),
      daily_records:week==='2026-W46'&&(!member||member==='he')?[dailyRecord]:[],
      weekly_reports:week!=='2026-W46'&&(!member||member==='lu')?[weeklyRecord]:[],
      weekly_timetable:{weeks,records:weeks.filter(value=>['2026-W45','2026-W44'].includes(value)&&(!member||member==='lu')).map(value=>({member_id:'lu',member_name:'陆梓健',week:value,readable:true,url:'#team?week='+value+'&member=lu&report=weekly',original_url:'/progress/api/report-source/weekly/lu/'+value,original_label:'下载周报原件',attachments:[]}))},
      selected_daily:week==='2026-W46'&&member==='he'&&url.searchParams.get('date')==='2026-11-14'?{date:'2026-11-14',fields:reportFields,attachment_count:2}:null,
      selected_weekly:member==='lu'&&url.searchParams.get('report')==='weekly'?{fields:weeklyReportFields}:null};
    if((slowWeekly&&week==='2026-W46'&&!member)||(slowDaily&&week==='2026-W45'&&member==='empty-a'))setTimeout(()=>json(payload),120);
    else json(payload);
    return;
  }
  if(url.pathname.startsWith('/progress/api/report-source/')) {
    const filename=url.pathname.endsWith('/1')?'evidence.txt':url.pathname.endsWith('/2')?'results.pdf':'2026-11-14.md';
    response.writeHead(200,{'Content-Type':'application/octet-stream','Content-Disposition':'attachment; filename="'+filename+'"'});return response.end('synthetic source bytes');
  }
  let filename=url.pathname==='/progress/'?'index.html':/^\/progress\/assets\/(app\.js|activity\.js|digest\.js|rhythm\.js|d3\.v7\.min\.js|style\.css|activity\.css|digest\.css|rhythm\.css)$/.exec(url.pathname)?.[1];
  if(url.pathname==='/platform-theme.css')filename='../../research-data-center-next/static/platform-theme.css';
  if(url.pathname==='/astronomy/hubble-1024.webp')filename='../../research-data-center-next/static/astronomy/hubble-1024.webp';
  if(!filename){response.writeHead(404);return response.end();}
  response.writeHead(200,{'Content-Type':filename.endsWith('.css')?'text/css':filename.endsWith('.js')?'text/javascript':filename.endsWith('.webp')?'image/webp':'text/html; charset=utf-8'});
  response.end(fs.readFileSync(path.join(web,filename)));
});

async function main(){
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const base='http://127.0.0.1:'+server.address().port, browser=await chromium.launch({headless:true});
  try {
    for(const width of [1440,390,320]) {
      revision=1;failDaily=false;deferred=false;stress=false;slowWeekly=slowDaily=false;
      const page=await browser.newPage({viewport:{width,height:1000},hasTouch:width<600});
      page.setDefaultTimeout(5000);await page.clock.install();
      const errors=[];page.on('pageerror',error=>errors.push(error.message));
      await page.goto(base+'/progress/#team?week=2026-W45');
      const he=()=>page.locator('#daily-feed [data-member="he"]');
      await he().locator('dd').getByText(fields.done,{exact:true}).waitFor();
      assert.equal(await he().getAttribute('open'),'');
      assert.equal(await he().locator('dl > div').count(),4);
      assert.equal(await he().locator('a[download]').count(),3);
      assert.equal(await page.locator('#activity-weekly-list [data-member="lu"]').getAttribute('open'),null,'weekly originals start collapsed');
      const weeklyCard=page.locator('#activity-weekly-list [data-member="lu"]');
      assert.equal(await weeklyCard.locator('.report-entry-preview').innerText(),weeklyFirstItem);
      assert.equal(await weeklyCard.locator('.report-entry-highlights').count(),0);
      await weeklyCard.locator('summary').click();
      const weeklyBody=weeklyCard.locator('dl > div');
      assert.equal(await weeklyBody.nth(0).locator('dd > p').count(),4);
      assert.equal(await weeklyBody.nth(0).locator('dd > p').first().innerText(),weeklyFirstItem,'known field prefix remains in the first numbered paragraph');
      assert.equal(await weeklyBody.nth(0).locator('dd > p').allTextContents().then(parts=>parts.join('')),weeklyFields.done,'sentence punctuation and every character remain intact');
      assert.match(await weeklyBody.nth(0).innerText(),/4）保留全部原始证据/);
      assert.equal(await weeklyBody.nth(2).locator('dd > p').count(),2);
      assert.equal(await weeklyBody.nth(1).locator('dd > p').count(),1);
      assert.equal(await weeklyBody.nth(1).locator('dd').innerText(),weeklyFields.results);
      await weeklyCard.locator('summary').click();
      assert.match(await page.locator('#activity-week').innerText(),/2026-W45/);
      assert.match(await page.locator('#daily-week').innerText(),/2026-W46/);
      assert.equal(await page.locator('.progress-image-credit').count(),0);
      assert.equal(await page.locator('#daily-coverage, #activity-weekly-coverage').count(),0);
      assert.equal(await page.locator('#activity-grid [data-member="he"] .activity-day').count(),7);
      assert.equal(await page.locator('#weekly-timetable [data-member="lu"] .activity-day').count(),4);
      assert.equal(await page.locator('#weekly-timetable [data-member="lu"] a').count(),2);
      assert.equal(await page.locator('#activity-status').innerText(),'');
      assert.equal(await page.locator('#activity-weekly-status').innerText(),'');
      assert.equal(await page.locator('#weekly-archive').getAttribute('open'),null);

      const navigation=page.getByRole('navigation',{name:'科研进度导航'});
      await navigation.getByRole('link',{name:'提交日报'}).click();
      await page.locator('#daily-member').selectOption('he');
      await page.locator('#daily-field-done').fill('独立于阅读筛选的何锋草稿');
      await page.locator('#daily-attachments').setInputFiles([{name:'draft.txt',mimeType:'text/plain',buffer:Buffer.from('draft')},{name:'draft.csv',mimeType:'text/csv',buffer:Buffer.from('key,value\na,1')}]);
      await navigation.getByRole('link',{name:'团队进度'}).click();
      await page.locator('#activity-weekly-list').getByText('本周尚未收到周报',{exact:true}).waitFor();
      await page.locator('#activity-member').selectOption('he');
      await page.waitForFunction(()=>document.querySelector('#activity-member').value==='he');
      await page.locator('#activity-weekly-list').getByRole('link',{name:/最近已发布周报 · 2026-W45/}).click();
      await page.locator('#activity-week').getByText(/2026-W45/).waitFor();
      assert.equal(await page.locator('#activity-member').inputValue(),'','latest team report clears only the weekly member filter');
      assert.equal(await page.locator('#daily-member').inputValue(),'he');
      await page.locator('#weekly-archive > summary').click();
      assert.match(await he().innerText(),/合成日报/);
      await page.locator('#activity-member').selectOption('lu');
      await page.waitForFunction(()=>document.querySelector('#activity-member').value==='lu'&&document.querySelector('#activity-weekly-list [data-member="lu"]'));
      assert.match(await he().innerText(),/合成日报/);
      await page.locator('#activity-prev').click();
      await page.locator('#activity-week').getByText(/2026-W44/).waitFor();
      assert.match(await page.locator('#daily-week').innerText(),/2026-W46/);
      assert.match(await he().innerText(),/合成日报/);
      await page.locator('#daily-prev').click();
      await page.locator('#daily-week').getByText(/2026-W45/).waitFor();
      assert.match(await page.locator('#activity-week').innerText(),/2026-W44/);
      assert.equal(await page.locator('#daily-feed [data-member]').count(),0);
      await page.locator('#daily-current').click();
      await he().waitFor();

      // Two filters can produce byte-identical empty API responses; controls still follow the route.
      for(const id of ['empty-a','empty-b']) {
        await page.locator('#daily-member-filter').selectOption(id);
        await page.waitForFunction(id=>document.querySelector('#daily-member-filter').value===id,id);
        assert.equal(await page.locator('#daily-feed [data-member]').count(),0);
      }
      await page.locator('#daily-member-filter').selectOption('he');await he().waitFor();
      for(const id of ['empty-a','empty-b']) {
        await page.locator('#activity-member').selectOption(id);
        await page.waitForFunction(id=>document.querySelector('#activity-member').value===id,id);
      }
      await page.locator('#activity-member').selectOption('lu');
      await page.locator('#activity-next').click();
      await page.locator('#activity-week').getByText(/2026-W45/).waitFor();
      assert.equal(await page.locator('#daily-member').inputValue(),'he');
      assert.equal(await page.locator('#daily-field-done').inputValue(),'独立于阅读筛选的何锋草稿');
      assert.equal(await page.locator('#daily-attachments').evaluate(input=>input.files.length),2);
      await page.locator('#weekly-archive > summary').click();
      await page.locator('#team-list button').filter({has:page.getByText('2026-W44',{exact:true})}).click();
      await page.locator('#activity-week').getByText(/2026-W44/).waitFor();
      assert.match(await page.locator('#daily-week').innerText(),/2026-W46/);
      assert.match(await he().innerText(),/合成日报/);
      await page.locator('#weekly-archive > summary').click();

      // A legacy daily source read must not change the currently selected weekly period/member.
      await page.evaluate(()=>{location.hash='#team?week=2026-W46&member=he&date=2026-11-14';});
      await he().locator('dd').getByText(fields.done,{exact:true}).waitFor();
      assert.match(await page.locator('#activity-week').innerText(),/2026-W44/);
      assert.equal(await page.locator('#activity-member').inputValue(),'lu');
      await he().locator('summary').click();
      await he().locator('summary').focus();revision++;
      await page.clock.runFor(30001);
      await page.waitForFunction(()=>document.activeElement?.closest('[data-report-key]')?.dataset.member==='he');
      assert.equal(await he().getAttribute('open'),null,'refresh preserves a deliberate collapse');
      await he().locator('summary').click();
      for(const name of ['evidence.txt','results.pdf']) {
        const event=page.waitForEvent('download');await he().getByRole('link',{name:'附件 · '+name,exact:true}).click();
        const download=await event;assert.equal(download.suggestedFilename(),name);assert.ok(await download.path());
      }
      failDaily=true;await page.evaluate(()=>teamActivity.refresh());
      assert.match(await page.locator('#activity-status').innerText(),/暂时无法更新/);assert.match(await he().innerText(),/合成日报/);
      failDaily=false;await page.evaluate(()=>teamActivity.refresh());
      assert.doesNotMatch(await page.locator('#activity-status').innerText(),/暂时无法更新/);
      await page.locator('#daily-all-members').click();
      await page.waitForFunction(()=>document.querySelectorAll('#activity-grid .activity-member-row').length===4);
      await page.locator('#activity-grid [data-member="he"] a[data-period="2026-11-14"]').click();
      await page.waitForFunction(()=>document.querySelector('#activity-grid [data-member="he"] a[aria-current="date"]'));
      await page.locator('#weekly-timetable [data-member="lu"] a[data-period="2026-W44"]').click();
      await page.waitForFunction(()=>document.querySelector('#activity-weekly-list [data-member="lu"]').open);
      assert.equal(await page.locator('#weekly-timetable [data-member="lu"] a[data-period="2026-W44"]').getAttribute('aria-current'),'true');
      assert.match(await he().innerText(),/合成日报/);
      // Link contexts must follow the new filter even when the other request finishes first.
      slowWeekly=true;
      await page.evaluate(()=>{location.hash='#team?week=2026-W46&daily_week=2026-W46&daily_member=he';});
      await page.locator('#activity-week').getByText(/2026-W46/).waitFor();
      let timelineURL=new URL((await page.locator('#activity-grid [data-member="he"] a[data-period="2026-11-14"]').getAttribute('href')),base+'/progress/');
      assert.equal(new URLSearchParams(timelineURL.hash.split('?')[1]).get('week'),'2026-W46');
      await page.locator('#activity-grid [data-member="he"] a[data-period="2026-11-14"]').click();
      await page.waitForFunction(()=>document.querySelector('#daily-feed [data-member="he"]')?.open);
      assert.match(await page.locator('#activity-week').innerText(),/2026-W46/);
      slowWeekly=false;slowDaily=true;
      await page.evaluate(()=>{location.hash='#team?week=2026-W46&daily_week=2026-W45&daily_member=empty-a';});
      await page.locator('#daily-week').getByText(/2026-W45/).waitFor();
      timelineURL=new URL((await page.locator('#weekly-timetable [data-member="lu"] a[data-period="2026-W45"]').getAttribute('href')),base+'/progress/');
      const crossParams=new URLSearchParams(timelineURL.hash.split('?')[1]);
      assert.equal(crossParams.get('daily_week'),'2026-W45');assert.equal(crossParams.get('daily_member'),'empty-a');
      await page.locator('#weekly-timetable [data-member="lu"] a[data-period="2026-W45"]').click();
      await page.locator('#activity-week').getByText(/2026-W45/).waitFor();
      assert.match(await page.locator('#daily-week').innerText(),/2026-W45/);
      assert.equal(await page.locator('#daily-member-filter').inputValue(),'empty-a');
      slowDaily=false;
      await page.locator('#daily-current').click();
      await page.locator('#daily-week').getByText(/2026-W46/).waitFor();
      await page.locator('#daily-member-filter').selectOption('he');await he().waitFor();
      for(const selector of ['#activity-grid a','#weekly-timetable a']) {
        const sizes=await page.locator(selector).evaluateAll(items=>items.map(item=>({width:item.getBoundingClientRect().width,height:item.getBoundingClientRect().height})));
        assert.ok(sizes.every(size=>size.width>=43.9&&size.height>=43.9),'date targets must be at least 44px');
      }
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${width}px must not overflow`);
      if(process.env.RESEARCH_DIGEST_SCREENSHOTS)await page.screenshot({path:path.join(process.env.RESEARCH_DIGEST_SCREENSHOTS,`report-views-${width}.png`),fullPage:true});
      stress=true;revision++;await page.evaluate(()=>teamActivity.refresh());
      assert.match(await he().locator('.report-entry-preview').textContent(),/首段结束$/);
      assert.doesNotMatch(await he().locator('.report-entry-preview').textContent(),/…$/);
      assert.match(await he().locator('dd').first().innerText(),/第二段完整正文结束/);
      for(const scale of [1,2]) {
        await page.evaluate(scale=>{document.documentElement.style.fontSize=(15*scale)+'px';document.querySelectorAll('#weekly-progress details, #activity-records details').forEach(item=>item.open=true);},scale);
        const overflow=await page.evaluate(()=>[...document.querySelectorAll('#weekly-progress *,#activity-records *')].filter(item=>item instanceof HTMLElement&&item.clientWidth>0&&item.getClientRects().length&&!item.classList.contains('report-sr-only')&&getComputedStyle(item).display!=='none'&&item.scrollWidth>item.clientWidth+1).map(item=>({tag:item.tagName,class:item.className,width:item.clientWidth,scroll:item.scrollWidth,parent:item.parentElement.className,html:item.outerHTML.slice(0,180)})).slice(0,12));
        assert.deepEqual(overflow,[],`${width}px ${scale*100}% report internals must wrap`);
        assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${width}px ${scale*100}% root overflow`);
      }
      stress=false;
      assert.deepEqual(errors,[]);await page.close();

      for(const suffix of ['?week=2026-W46&member=he&date=2026-11-14','?week=2026-W45&member=lu&report=weekly','?week=2026-W45']) {
        const fresh=await browser.newPage({viewport:{width,height:1000},hasTouch:width<600});fresh.setDefaultTimeout(5000);
        await fresh.goto(base+'/progress/#team'+suffix);
        await fresh.locator('#daily-feed [data-member="he"] dd').getByText(fields.done,{exact:true}).waitFor();
        assert.match(await fresh.locator('#daily-week').innerText(),/2026-W46/);
        if(suffix.includes('report=weekly')) {
          const weekly=fresh.locator('#activity-weekly-list [data-member="lu"]');
          await weekly.locator('dd').getByText(weeklyFirstItem,{exact:true}).waitFor();assert.equal(await weekly.getAttribute('open'),'');
        }
        await fresh.close();
      }
      deferred=true;
      const lazy=await browser.newPage({viewport:{width,height:1000}});lazy.setDefaultTimeout(5000);
      await lazy.goto(base+'/progress/#team');
      await lazy.locator('#daily-feed').getByRole('link',{name:'阅读全文 ↗'}).click();
      await lazy.locator('#daily-feed [data-member="he"] dd').getByText(fields.done,{exact:true}).waitFor();
      assert.equal(await lazy.locator('#daily-feed [data-member="he"] a[download]').count(),3);
      await lazy.close();deferred=false;
      console.log(`PASS ${width}px: independent periods/members, readable feed, original/attachments, fresh legacy links, focus/state retention and write-identity isolation`);
    }
    assert.ok(methods.every(method=>method==='GET'),'read acceptance must not submit reports');
  }finally{await browser.close();server.close();}
}
main().catch(error=>{console.error(error);server.close();process.exitCode=1;});
