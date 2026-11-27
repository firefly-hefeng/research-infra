/* Real portal HTML/CSS/JS with synthetic HTTP data; never calls DeepSeek or writes reports. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const {chromium} = require(process.env.RESEARCH_PLAYWRIGHT_MODULE || 'playwright');

const staticRoot = path.resolve(__dirname, '../static');
const empty = () => ({done:[], results:[], blockers:[], next:[]});
const entry = text => ({text,source_ids:['daily-1','direction-1'],evidence:[]});
const doc = {schema_version:1,revision:1,fingerprint:'synthetic-home-1',engine:'DeepSeek',generated_at:'2026-11-15T02:00:00Z',
  period:{from:'2026-10-19',to:'2026-11-15',days:28},
  team:{done:[entry('已整理团队的数据基线')],results:[entry('已归档可追溯的实验记录')],
    blockers:[entry('尚需核对设备差异')],next:[entry('对照验证输入范围')]},
  members:[{id:'alice',name:'甲同学',report_count:2,last_report_at:'2026-11-15',...empty(),done:[entry('整理模型与数据接口')]},
    {id:'bob',name:'乙同学',report_count:1,last_report_at:'2026-11-14',...empty(),results:[entry('取得可复查的初步实验结果')]},
    {id:'carol',name:'丙同学',report_count:1,last_report_at:'2026-11-14',...empty(),blockers:[entry('只有阻塞记录，等待设备核对')]},
    {id:'dave',name:'丁同学',report_count:0,...empty()}],
  directions:[{id:'voice',title:'声音基础研究',report_count:2,...empty(),done:[entry('完成声音研究基线')],baseline:{url:'#directions?item=voice'}},
    {id:'sleep',title:'睡眠研究',report_count:0,...empty(),baseline:{url:'#directions?item=sleep'}}],
  unassigned:{...empty(),next:[entry('进一步梳理待归类的平台工作')]},
  sources:[{id:'daily-1',kind:'daily',title:'合成日报原文',member_id:'alice',date:'2026-11-15',url:'#team',sha256:'synthetic'},
    {id:'daily-2',kind:'daily',title:'乙同学日报',member_id:'bob',date:'2026-11-14',url:'#team',sha256:'synthetic'},
    {id:'weekly-1',kind:'weekly',title:'合成周报原文',member_id:'alice',week:'2026-W46',url:'#team',sha256:'synthetic'},
    {id:'direction-1',kind:'direction',title:'合成方向文书',url:'#directions',sha256:'synthetic'},
    {id:'external-1',kind:'daily',title:'禁止站外引用跳转',member_id:'carol',date:'2026-11-15',url:'https://untrusted.invalid/progress/#team',sha256:'synthetic'}],
  counts:{members:4,active_members:3,daily:3,weekly:1,directions:2}};
let payload, failure = false, requests = 0;
const methods = [];

const server = http.createServer((request,response) => {
  methods.push(request.method);
  const url = new URL(request.url,'http://127.0.0.1');
  const json = (data,status=200) => {response.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store'});response.end(JSON.stringify(data));};
  if (url.pathname === '/progress/api/progress-digest') {
    requests++;
    return failure ? json({error:{code:'synthetic_unavailable',message:'Synthetic interruption'}},503) : json(payload);
  }
  if (url.pathname === '/api/session') return json({auth_enabled:false,authenticated:true});
  if (url.pathname === '/api/summary') return json({total:0,by_kind:{},by_status:{},by_server:{},categories:[],sources:[],scope:{}});
  if (url.pathname === '/api/platform/servers') return json({mode:'not_configured',servers:[]});
  if (url.pathname === '/api/platform/research') return json({models:[],research_tracks:[],partners:[],sources:[]});
  if (url.pathname === '/api/workspace-docs') return json({items:[]});
  if (url.pathname === '/progress/') {response.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});return response.end('<h1>合成进度来源入口</h1>');}
  const shared = /^\/progress\/assets\/(d3\.v7\.min\.js|rhythm\.js|rhythm\.css)$/.exec(url.pathname);
  if (shared) {
    response.writeHead(200,{'Content-Type':shared[1].endsWith('.js')?'text/javascript':'text/css'});
    return response.end(fs.readFileSync(path.resolve(__dirname,'../../research-progress-next/web',shared[1])));
  }
  const filename = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
  const permitted = /^(?:index\.html|workspace\.js|app\.js|styles\.css|platform-theme\.css|workspace\.css|astronomy\/hubble-(?:640|1024)\.webp)$/;
  if (!permitted.test(filename)) {response.writeHead(404);return response.end();}
  const file = path.join(staticRoot,filename);
  if (!fs.existsSync(file)) {response.writeHead(404);return response.end();}
  const contentType = filename.endsWith('.js')?'text/javascript':filename.endsWith('.css')?'text/css':filename.endsWith('.webp')?'image/webp':'text/html; charset=utf-8';
  response.writeHead(200,{'Content-Type':contentType});
  response.end(fs.readFileSync(file));
});

async function main() {
  await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
  const base = 'http://127.0.0.1:' + server.address().port;
  const browser = await chromium.launch({headless:true});
  try {
    for (const width of [1440,390,320]) {
      requests = 0;
      failure = false;
      payload = {document:structuredClone(doc),status:{state:'ready',last_success_at:doc.generated_at}};
      payload.document.team.done.push({...entry('<img src=x onerror="window.injected=true">'),source_ids:['external-1']});
      const page = await browser.newPage({viewport:{width,height:1000},hasTouch:width<600});
      page.setDefaultTimeout(5000);
      await page.clock.install();
      const errors = [];
      page.on('pageerror',error => errors.push(error.message));
      await page.goto(base + '/');
      await page.locator('#home-progress-members > details').last().waitFor();
      assert.equal(await page.locator('#home-progress-members > details').count(),4);
      assert.match(await page.locator('#home-progress-status').innerText(),/4 位成员 · 3 份日报、1 份周报/);
      assert.match(await page.locator('[data-member="dave"] summary').innerText(),/本期尚未收到研究报告/);
      assert.match(await page.locator('[data-member="carol"] summary').innerText(),/只有阻塞记录/);
      assert.equal(await page.locator('.home-team-summary > section').count(),4);
      assert.equal(await page.locator('#home-progress-rhythm [data-rhythm-kind]').count(),2);
      assert.equal(await page.locator('#home-progress-rhythm [data-rhythm-kind="daily"] .report-rhythm-record').evaluateAll(rows=>rows.reduce((n,row)=>n+Number(row.dataset.count),0)),3);
      assert.equal(await page.locator('#home-progress-rhythm [data-rhythm-kind="weekly"] .report-rhythm-record').evaluateAll(rows=>rows.reduce((n,row)=>n+Number(row.dataset.count),0)),1);
      assert.equal(await page.locator('.home-team-overview').getAttribute('open'),null);
      assert.equal(await page.locator('#home-progress-members details[open]').count(),0);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),`collapsed page overflow at ${width}px`);
      if (process.env.RESEARCH_DIGEST_SCREENSHOTS) await page.screenshot({path:path.join(process.env.RESEARCH_DIGEST_SCREENSHOTS,`home-progress-${width}.png`),fullPage:true});

      // Hash-only report and direction URLs belong to the progress app, not the portal router.
      const team = page.locator('.home-team-overview');
      await team.locator(':scope > summary').focus();
      await page.keyboard.press('Enter');
      const report = team.getByRole('link',{name:'合成日报原文'}).first();
      const direction = team.getByRole('link',{name:'合成方向文书'}).first();
      assert.equal(await report.getAttribute('href'),base+'/progress/#team');
      assert.equal(await direction.getAttribute('href'),base+'/progress/#directions');
      assert.equal(await page.locator('#home-progress img, #home-progress script').count(),0);
      assert.equal(await page.locator('#home-progress a[href*="untrusted.invalid"]').count(),0);
      assert.equal(await page.evaluate(() => window.injected),undefined);
      await page.locator('[data-member="alice"] > summary').click();
      await page.locator('#home-progress-directions > summary').click();
      await page.locator('[data-direction="voice"] > summary').click();
      assert.equal(await page.locator('[data-direction="voice"] a.workspace-link').getAttribute('href'),base+'/progress/#directions?item=voice');
      assert.match(await page.locator('[data-direction="sleep"] > summary').innerText(),/近期暂无对应报告/);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),`expanded page overflow at ${width}px`);

      const refresh = async () => {
        await page.locator('#refresh').click();
        await page.waitForFunction(() => !document.querySelector('#refresh').disabled);
      };
      payload.document.revision++;
      payload.document.team.done[0].text = '动态更新后的整体进展';
      await refresh();
      assert.match(await page.locator('.home-team-summary').innerText(),/动态更新后的整体进展/);
      assert.equal(await team.getAttribute('open'),'');
      assert.equal(await page.locator('[data-member="alice"]').getAttribute('open'),'');
      assert.equal(await page.locator('[data-direction="voice"]').getAttribute('open'),'');
      payload.status.state = 'running';
      await refresh();
      assert.match(await page.locator('#home-progress-status').innerText(),/正在整理新记录/);
      payload.status.state = 'failed';
      await refresh();
      assert.match(await page.locator('#home-progress-status').innerText(),/更新暂未完成/);
      assert.match(await team.innerText(),/动态更新后的整体进展/);
      payload.status.state = 'ready';
      await refresh();
      failure = true;
      await refresh();
      assert.match(await page.locator('#home-progress-status').innerText(),/暂时无法更新/);
      assert.equal(await page.locator('#home-progress-members > details').count(),4);
      failure = false;
      await refresh();
      assert.match(await page.locator('#home-progress-status').innerText(),/DeepSeek ·/);
      assert.doesNotMatch(await page.locator('#home-progress-status').innerText(),/暂时无法更新/);

      payload.document.revision++;
      payload.document.engine = 'DeepSeek V4 Pro · Max';
      payload.document.research_brief = {overview:[entry('研究大局：先验证模型是否保留关键表征')],
        findings:[entry('关键发现：当前差异仍待独立验证')],constraints:[entry('共同约束：数据时间轴尚不完整')],
        priorities:[entry('建议先完成表征可读性验证，再增加复杂模块')]};
      await refresh();
      assert.match(await page.locator('.home-team-summary').innerText(),/研究大局：先验证模型/);
      assert.match(await page.locator('#home-progress-status').innerText(),/DeepSeek V4 Pro · Max/);
      assert.equal(await page.locator('.home-team-summary > section').count(),4);

      const beforePoll = requests;
      payload.document.revision++;
      await page.locator('[data-member="alice"] > summary').focus();
      const pollResponse = page.waitForResponse(response => response.url().endsWith('/progress/api/progress-digest'));
      await page.clock.runFor(30001);
      await pollResponse;
      await page.waitForFunction(() => document.activeElement?.closest('[data-member]')?.dataset.member === 'alice');
      assert.ok(requests > beforePoll,'visible homepage must poll every 30 seconds');
      await page.evaluate(() => Object.defineProperty(document,'hidden',{configurable:true,get:()=>true}));
      const hiddenRequests = requests;
      await page.clock.runFor(30001);
      assert.equal(requests,hiddenRequests,'hidden homepage must not poll');
      await page.evaluate(() => {Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});document.dispatchEvent(new Event('visibilitychange'));});
      await page.waitForFunction(() => document.querySelectorAll('#home-progress-members > details').length === 4);
      for (const state of ['pending','disabled']) {
        payload = {document:null,status:{state}};
        await refresh();
        assert.equal(await page.locator('#home-progress-overview').innerText(),'');
        assert.equal(await page.locator('#home-progress-members > details').count(),0);
        assert.equal(await page.locator('#home-progress-direction-list').innerText(),'');
        assert.equal(await page.locator('#home-progress-directions').isHidden(),true);
        assert.match(await page.locator('#home-progress-status').innerText(),state==='pending'?/等待首次整理/:/自动整理尚未启用/);
        payload = {document:structuredClone(doc),status:{state:'ready'}};
        await refresh();
        assert.equal(await page.locator('#home-progress-members > details').count(),4);
      }
      assert.deepEqual(errors,[]);
      // Follow both actual hrefs to ensure navigation leaves the homepage router.
      await page.locator('.home-team-overview > summary').click();
      await page.locator('.home-team-overview').getByRole('link',{name:'合成日报原文'}).first().click();
      assert.equal(page.url(),base+'/progress/#team');
      await page.goto(base+'/');
      await page.locator('#home-progress-members > details').last().waitFor();
      await page.locator('.home-team-overview > summary').click();
      await page.locator('.home-team-overview').getByRole('link',{name:'合成方向文书'}).first().click();
      assert.equal(page.url(),base+'/progress/#directions');
      assert.deepEqual(errors,[]);
      await page.close();
      console.log(`PASS ${width}px: four members, report/direction source links, state retention/recovery/clearing, refresh lifecycle, safe content and responsive layout`);
    }
    assert.ok(methods.every(method => method==='GET'),'acceptance is read-only');
  } finally {await browser.close();server.close();}
}
main().catch(error => {console.error(error);server.close();process.exitCode=1;});
