/* Browser regression against synthetic sources; does not write reports or call a model. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const {chromium} = require(process.env.RESEARCH_PLAYWRIGHT_MODULE || 'playwright');

const root = path.resolve(__dirname, '../web');
const roster = [{id:'alice', name:'甲同学'}, {id:'bob', name:'乙同学'}, {id:'carol',name:'丙同学'}, {id:'dave',name:'丁同学'}];
const dates = ['2026-11-09','2026-11-10','2026-11-11','2026-11-12','2026-11-13','2026-11-14','2026-11-15'];
const fields = {done:'已完成原始日报', results:'原文结果', blockers:'仍需核对', next:'继续检验'};
const empty = () => ({done:[], results:[], blockers:[], next:[]});
const longQuoteUrl = 'https://example.invalid/evidence/' + 'unbroken'.repeat(32);
const item = {text:'已建立可复核的数据基线 <img src=x onerror=alert(1)>', source_ids:['daily-1','weekly-1'],
  evidence:[{source_id:'daily-1', quote:'保留原文 <script>window.injected=true</script>\n<' + longQuoteUrl + '>'}]};
const doc = {schema_version:1, revision:1, engine:'DeepSeek V4 Pro · Max', generated_at:'2026-11-14T02:00:00Z',
  fingerprint:'synthetic', period:{from:'2026-10-18',to:'2026-11-14',days:28},
  team:{...empty(), done:[item], next:[{...item,text:'检验新数据的适用范围'}]},
  members:[{id:'alice',name:'甲同学',report_count:2,last_report_at:'2026-11-14',...empty(),done:[item]},
    {id:'bob',name:'乙同学',report_count:0,...empty()},
    {id:'carol',name:'丙同学',report_count:1,...empty(),next:[{text:'安排跨设备对照',source_ids:['daily-3'],evidence:[]}]},
    {id:'dave',name:'丁同学',report_count:1,...empty(),blockers:[{text:'核对设备录音差异',source_ids:['daily-2'],evidence:[]}]}],
  directions:[{id:'voice',title:'声音基础研究',report_count:1,...empty(),done:[item],
    baseline:{question:'声音可表达哪些信号？',progress:'旧文书中的研究基线',next:'历史计划',updated_at:'2026-10-20',url:'/progress/#directions?item=voice'}},
    {id:'sleep',title:'睡眠研究',report_count:0,...empty(),baseline:{question:'睡眠的研究问题',updated_at:'2026-10-21',url:'/progress/#directions?item=sleep'}}],
  unassigned:{...empty(),next:[{...item,text:'梳理尚未归类的平台工作'}]},
  sources:[{id:'daily-1',kind:'daily',title:'甲同学 · 2026-11-14',url:'/progress/#team?week=2026-W46&member=alice&date=2026-11-14',
    original_url:'/progress/api/report-source/daily-1',date:'2026-11-14',sha256:'synthetic'},
    {id:'weekly-1',kind:'weekly',title:'甲同学 · 2026-W46',url:'/progress/#team?week=2026-W46&member=alice&report=weekly',week:'2026-W46',
      original_url:'https://untrusted.invalid/api/report-source/x',sha256:'synthetic'},
    {id:'daily-2',kind:'daily',title:'丁同学 · 2026-11-13',date:'2026-11-13',url:'/progress/#team?week=2026-W46&member=dave&date=2026-11-13',sha256:'synthetic'},
    {id:'daily-3',kind:'daily',title:'丙同学 · 2026-11-14',date:'2026-11-14',url:'/progress/#team?week=2026-W46&member=carol&date=2026-11-14',sha256:'synthetic'}],
  counts:{members:4,active_members:3,daily:3,weekly:1,directions:2}};
let payload, networkFailure = false, digestRequests = 0;

const server = http.createServer((request,response) => {
  const url = new URL(request.url, 'http://127.0.0.1');
  const json = data => {response.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'});response.end(JSON.stringify(data));};
  if (url.pathname === '/progress/api/public') return json({team_name:'合成进展回归',members:roster,
    week:'2026-W46',date:'2026-11-14',timezone:'Asia/Shanghai',max_upload_bytes:20971520,max_report_bytes:65536,
    daily_team_sharing:true,max_daily_attachments:8,max_daily_attachment_bytes:20971520});
  if (url.pathname === '/progress/api/progress-digest') {
    digestRequests++;
    if (networkFailure) {response.writeHead(503,{'Content-Type':'application/json'});return response.end('{"error":"synthetic failure"}');}
    return json(payload);
  }
  if (url.pathname === '/progress/api/team') return json({items:['2026-W46','2026-W45'].map(week=>({week,submitted:1,expected:4}))});
  if (/^\/progress\/api\/team\/2026-W(?:45|46)$/.test(url.pathname)) return json({week:url.pathname.split('/').pop(),date_range:['2026-11-09','2026-11-15'],engine_label:'合成周报',submitted:1,received:1,expected:4,members:[],overview:['阶段性实验已归档'],team_risks:[],next_actions:[]});
  if (url.pathname === '/progress/api/team/activity') {
    const week = url.searchParams.get('week') || '2026-W46';
    const member = url.searchParams.get('member');
    const dailyRecords = week === '2026-W45' ? [] : ['alice','carol','dave'].map(id=>({member_id:id,member_name:roster.find(person=>person.id===id).name,date:id==='dave'?'2026-11-13':'2026-11-14',fields})).filter(record=>!member||record.member_id===member);
    return json({week,current_week:'2026-W46',dates:week==='2026-W45'?dates.map(date=>date.replace(/\d{2}$/,day=>String(Number(day)-7).padStart(2,'0'))):dates,weekly_revision:'1',
    members:roster.map(member => ({...member,days:week==='2026-W45'?[]:['alice','carol'].includes(member.id) ? ['2026-11-14'] : member.id==='dave'?['2026-11-13']:[],weekly_readable:member.id === 'alice',weekly_status:member.id === 'alice'?'ready':'missing'})),
    selected_daily:url.searchParams.get('date') ? {date:'2026-11-14',fields} : null,
    daily_records:dailyRecords,weekly_reports:!member||member==='alice'?[{member_id:'alice',member_name:'甲同学',week,status:'ready',fields:{...fields,done:'已完成原始周报'}}]:[],
    selected_weekly:{fields:{...fields,done:'已完成原始周报'}}});
  }
  if (url.pathname === '/progress/api/directions') return json({items:[],unavailable:[]});
  let filename = url.pathname === '/progress/' ? 'index.html' : /^\/progress\/assets\/(app\.js|activity\.js|digest\.js|rhythm\.js|d3\.v7\.min\.js|style\.css|activity\.css|digest\.css|rhythm\.css)$/.exec(url.pathname)?.[1];
  if (url.pathname === '/platform-theme.css') filename = '../../research-data-center-next/static/platform-theme.css';
  if (url.pathname === '/astronomy/hubble-1024.webp') filename = '../../research-data-center-next/static/astronomy/hubble-1024.webp';
  if (!filename) {response.writeHead(404);return response.end();}
  response.writeHead(200,{'Content-Type':filename.endsWith('.css')?'text/css':filename.endsWith('.js')?'text/javascript':'text/html; charset=utf-8'});
  response.end(fs.readFileSync(path.join(root,filename)));
});

async function main() {
  await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
  const base = 'http://127.0.0.1:' + server.address().port;
  const browser = await chromium.launch({headless:true});
  try {
    for (const width of [1440,390,320]) {
      payload = {document:null,status:{state:'pending'}};
      networkFailure = false;
      digestRequests = 0;
      const page = await browser.newPage({viewport:{width,height:1000},hasTouch:width<600});
      page.setDefaultTimeout(5000);
      const errors = [];
      page.on('pageerror',error => errors.push(error.message));
      await page.clock.install();
      await page.goto(base + '/progress/#team');
      await page.locator('#digest-status').getByText(/首次进展等待整理/).waitFor();
      assert.equal(await page.locator('#activity-records').getAttribute('open'),'');
      assert.deepEqual(await page.locator('#view-team > .progress-section').evaluateAll(nodes=>nodes.map(node=>node.id)),['weekly-progress','activity-records','progress-digest','research-context']);
      assert.equal(await page.locator('#activity-grid a[href*="report=weekly"]').count(),0);
      payload = {document:structuredClone(doc),status:{state:'ready',last_success_at:doc.generated_at}};
      await page.locator('#digest-refresh').click();
      await page.locator('#digest-period').getByText(/2026-10-18 至 2026-11-14/).waitFor();
      assert.equal(await page.locator('.digest-statement').count(),2);
      assert.equal(await page.locator('.digest-brief').getAttribute('data-brief-mode'),'records');
      assert.match(await page.locator('#digest-status').innerText(),/DeepSeek V4 Pro · Max/);
      assert.equal(await page.locator('[data-digest-key="member:bob"] strong').innerText(),'乙同学');
      assert.match(await page.locator('[data-digest-key="member:bob"]').innerText(),/近 28 天暂无报告/);
      assert.match(await page.locator('[data-digest-key="direction:sleep"]').innerText(),/近 28 天暂无关联记录/);
      assert.equal(await page.locator('#digest-content img, #digest-content script').count(),0);
      assert.equal(await page.locator('#digest-content a[href*="untrusted.invalid"]').count(),0);
      assert.equal(await page.locator('#research-context').getByText('旧文书中的研究基线',{exact:false}).isVisible(),false);
      assert.equal(await page.locator('#digest-content [data-digest-key^="direction:"]').count(),0);

      const member = page.locator('[data-digest-key="member:alice"]');
      await member.locator(':scope > summary').focus();
      await page.keyboard.press('Enter');
      await member.locator('.digest-sources > summary').first().click();
      assert.match(await member.locator('blockquote').first().innerText(),/<script>/);
      assert.equal(await member.locator('a.digest-original').getAttribute('href'),'api/report-source/daily-1');
      payload.document.revision = 2;
      payload.document.research_brief = {overview:[{...item,text:'围绕声音表征，团队已建立可复用基础，下一阶段需检验跨设备适用范围。'}],findings:[{...item,text:'已有证据支持当前输入条件下的复查，尚不能推定外部泛化。'}],constraints:[{...item,text:'关键约束是设备差异与对照设置，影响结论适用范围。'}],priorities:[{...item,text:'先统一对照条件，再扩展外部验证，避免放大现有证据。'}]};
      payload.document.members[0].done[0].text = '刷新后的实际进展';
      await page.evaluate(() => progressDigest.refresh());
      assert.equal(await member.getAttribute('open'),'');
      assert.equal(await member.locator('.digest-sources').first().getAttribute('open'),'');
      assert.match(await member.innerText(),/刷新后的实际进展/);
      assert.equal(await page.locator('.digest-brief').getAttribute('data-brief-mode'),'research');
      assert.equal(await page.locator('.digest-brief-field').count(),4);
      assert.equal(await page.evaluate(() => window.injected),undefined);

      payload.status = {state:'running',last_success_at:doc.generated_at};
      await page.evaluate(() => progressDigest.refresh());
      assert.match(await page.locator('#digest-status').innerText(),/正在整理/);
      payload.status = {state:'failed',last_success_at:doc.generated_at,error:'synthetic'};
      await page.evaluate(() => progressDigest.refresh());
      assert.match(await page.locator('#digest-status').innerText(),/本次整理失败/);
      assert.match(await member.innerText(),/刷新后的实际进展/);
      networkFailure = true;
      await page.evaluate(() => progressDigest.refresh());
      assert.match(await page.locator('#digest-status').innerText(),/进展读取失败，保留上次结果/);
      assert.match(await member.innerText(),/刷新后的实际进展/);
      networkFailure = false;
      payload.document = null;
      payload.status = {state:'disabled'};
      await page.evaluate(() => progressDigest.refresh());
      assert.equal(await page.locator('#digest-content .digest-entity').count(),0);
      assert.equal(await page.locator('#digest-period').innerText(),'');
      assert.match(await page.locator('#digest-status').innerText(),/尚未启用/);
      payload.document = doc;
      payload.status = {state:'ready',last_success_at:doc.generated_at};

      const previous = digestRequests;
      await page.clock.runFor(30001);
      await page.waitForFunction(expected => document.querySelector('#digest-status').dataset.state === 'ready',previous);
      assert.ok(digestRequests > previous,'30-second visible-page refresh must read the digest');
      await page.evaluate(() => Object.defineProperty(document,'hidden',{configurable:true,get:()=>true}));
      const hiddenRequests = digestRequests;
      await page.clock.runFor(30001);
      assert.equal(digestRequests,hiddenRequests,'hidden pages must not poll');
      await page.evaluate(() => {Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});document.dispatchEvent(new Event('visibilitychange'));});
      await page.waitForFunction(() => document.querySelector('#digest-status').dataset.state === 'ready');

      await page.locator('[data-digest-key="rhythm"] > summary').click();
      await page.locator('.report-rhythm svg').last().waitFor();
      assert.equal(await page.locator('.report-rhythm-figure[data-rhythm-kind="daily"] .report-rhythm-record').count(),28);
      assert.equal(await page.locator('.report-rhythm-figure[data-rhythm-kind="daily"] .report-rhythm-record[data-period="2026-11-14"]').getAttribute('data-count'),'2');
      assert.equal(await page.locator('.report-rhythm-figure[data-rhythm-kind="weekly"] .report-rhythm-record[data-period="2026-W46"]').getAttribute('data-count'),'1');
      assert.match(await page.locator('.report-rhythm-note').innerText(),/数量不代表科研完成度/);
      assert.match(await page.locator('.report-rhythm-figure[data-rhythm-kind="daily"] .report-rhythm-record[data-period="2026-11-13"] a').getAttribute('href'),/member=dave&date=2026-11-13/);
      await page.locator('.report-rhythm-figure[data-rhythm-kind="daily"] .report-rhythm-record[data-period="2026-11-14"] a').click();
      await page.waitForFunction(()=>document.querySelectorAll('#daily-feed [data-period="2026-11-14"]').length===2);
      await page.waitForFunction(()=>document.querySelectorAll('#activity-grid [data-selected-date="true"]').length===4);
      assert.equal(await page.locator('#activity-grid [data-selected-date="true"]').count(),4);
      assert.equal(await page.locator('#activity-report').isHidden(),true);

      if (await member.getAttribute('open') === null) await member.locator(':scope > summary').click();
      const citation = member.locator('.digest-sources').first();
      if (await citation.getAttribute('open') === null) await citation.locator(':scope > summary').click();
      await member.getByRole('link',{name:/日报原文/}).click();
      await page.locator('#daily-feed [data-member="alice"] dd').getByText('已完成原始日报',{exact:true}).waitFor();
      assert.equal(await page.locator('#activity-records').getAttribute('open'),'');
      assert.match(page.url(),/#team\?week=2026-W46&member=alice&date=2026-11-14$/);
      await member.getByRole('link',{name:/周报原文/}).click();
      await page.locator('#activity-weekly-list [data-member="alice"] dd').getByText('已完成原始周报',{exact:true}).waitFor();
      assert.equal(await page.locator('#activity-report').isHidden(),true);
      assert.equal(await page.locator('#weekly-archive').getAttribute('open'),null);
      await page.locator('#activity-prev').click();
      await page.locator('#activity-week').getByText(/2026-W45/).waitFor();
      assert.match(await page.locator('#daily-week').innerText(),/2026-W46/);
      assert.match(await page.locator('#daily-feed').innerText(),/已完成原始日报/);
      await page.locator('#weekly-archive > summary').click();
      await page.locator('#team-reader').getByText('2026-W45 团队周报',{exact:true}).waitFor();
      await page.locator('#activity-current').click();
      await page.locator('#activity-week').getByText(/2026-W46/).waitFor();
      await page.locator('#team-list button').filter({has:page.getByText('2026-W45',{exact:true})}).click();
      await page.locator('#activity-week').getByText(/2026-W45/).waitFor();
      await page.locator('#activity-current').click();
      await page.locator('#activity-week').getByText(/2026-W46/).waitFor();
      await page.getByRole('navigation',{name:'科研进度导航'}).getByRole('link',{name:'提交日报'}).click();
      await page.locator('#daily-field-done').fill('不会被动态整理覆盖的草稿');
      const stoppedRequests = digestRequests;
      await page.clock.runFor(30001);
      assert.equal(digestRequests,stoppedRequests,'leaving the team view must stop polling');
      await page.getByRole('navigation',{name:'科研进度导航'}).getByRole('link',{name:'团队进度'}).click();
      await page.locator('#digest-status').getByText(/依据报告与方向文书整理/).waitFor();
      assert.equal(await page.locator('#daily-field-done').inputValue(),'不会被动态整理覆盖的草稿');
      payload.document = structuredClone(doc);
      payload.document.research_brief = {
        overview:[{...item,text:'团队正把声音表征、数据基线与研究协作连成可复用的研究基础。下一阶段需要从能复查，推进到能在不同输入条件下验证。'}],
        findings:[{...item,text:'已有记录支持当前数据条件下的基线复查；跨设备适用性仍缺对照证据。'}],
        constraints:[{...item,text:'主要约束是设备差异与评估条件，关系到现有结论能推广到哪里。'}],
        priorities:[{...item,text:'先统一对照条件和证据记录，再做跨设备验证；根据结果决定下一轮数据扩展。'}],
      };
      await page.evaluate(() => progressDigest.refresh());
      await page.evaluate(() => {
        document.querySelectorAll('#digest-content details, #digest-directions details').forEach(element => {element.open = true;});
      });
      assert.ok(await page.locator('#digest-content blockquote').first().innerText().then(text=>text.includes(longQuoteUrl)), 'long evidence URLs must remain complete');
      for (const fontSize of ['100%','200%']) {
        await page.evaluate(value => {document.documentElement.style.fontSize = value;},fontSize);
        const overflow = await page.locator('#digest-content, #digest-content *, #digest-directions, #digest-directions *').evaluateAll(elements => elements
          .filter(element => element instanceof HTMLElement && element.checkVisibility() && element.clientWidth > 0 && element.scrollWidth > element.clientWidth + 2)
          .map(element => ({tag:element.tagName, class:element.className, width:element.clientWidth, scroll:element.scrollWidth})));
        assert.deepEqual(overflow,[],`digest content must wrap internally at ${width}px / ${fontSize}`);
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),`page overflow at ${width}px / ${fontSize}`);
      }
      await page.evaluate(() => {document.documentElement.style.removeProperty('font-size');});
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),`overflow at ${width}px`);
      if (process.env.RESEARCH_DIGEST_SCREENSHOTS) await page.screenshot({path:path.join(process.env.RESEARCH_DIGEST_SCREENSHOTS,`progress-digest-${width}.png`),fullPage:true});
      assert.deepEqual(errors,[]);
      await page.close();
      console.log(`PASS ${width}px: provenance, raw-report links, all members, state retention, refresh lifecycle and draft preservation`);
    }
  } finally {await browser.close();server.close();}
}
main().catch(error => {console.error(error);server.close();process.exitCode=1;});
