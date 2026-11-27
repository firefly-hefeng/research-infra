/* Real portal assets; synthetic GET-only services. No credentials, model calls or research writes. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const {chromium} = require(process.env.RESEARCH_PLAYWRIGHT_MODULE || 'playwright');

const staticRoot = path.resolve(__dirname, '../static');
const sourcePaths = ['/api/export.json','/api/research-guide','/api/platform/library','/api/platform/research',
  '/api/workspace-docs','/api/platform/servers','/progress/api/progress-digest','/progress/api/lab-review?format=json',
  '/progress/api/directions','/progress/api/direction-methods','/papers/api/export','/docs/agent-guide.md','/docs/agent-contract.json'];
const sentinel = 'SYNTHETIC_PRIVATE_SENTINEL_DO_NOT_EXPORT';
const guide = '# Agent 使用手册\n\n线上先登录飞书；读取现有证据，按各来源时间使用。\n';
const contract = {schema_version:'1.0',mode:'read_only_discovery',authentication:{browser:'Feishu session'},modules:['data','progress','papers']};
const resourceName = 'clinical_audio_date_label_lexical_20260929_r360';
const resourcePath = '/data/share/datasets/easystore/'+resourceName;
const longResource = {registry_id:'reg-d4858a95-59dd-4e4b-a5af-5ece1acece0a',asset_id:'asset-a93ad3d605a78bd5',kind:'dataset',subtype:'collection',
  display_name:resourceName,current_path:resourcePath,version_state:'unconfirmed',checks:{access:'readable',observed_at:'2026-10-27T08:27:50+00:00'},
  documentation:{summary:resourceName+'：已有研究数据的核查、索引或派生整理，具体来源需回原清单。本地台账主要数量为1，计数单位是全部可见文件，不等于数据样本。',
    category:'认知与语言研究',record_role:'clinical_audio_date_label_lexical_20260929_r360_collection',
    quantity:{primary_value:'1',unit:'全部可见文件（不等于数据样本）'}},
  evidence:[{label:'public_assets_20261018_clinical_audio_date_label_lexical_20260929_r360'}]};
let scenario = 'normal', authEnabled = false, active = 0, maxActive = 0;
const requests = [];
const server = http.createServer((req,res) => {
  const url = new URL(req.url,'http://127.0.0.1');
  const record = {path:url.pathname,target:req.url,method:req.method,headers:req.headers};
  requests.push(record);
  const json = (value,code=200) => {res.writeHead(code,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});res.end(JSON.stringify(value));};
  const text = (value,code=200,type='text/plain; charset=utf-8') => {res.writeHead(code,{'Content-Type':type,'Cache-Control':'no-store'});res.end(value);};
  if (req.method !== 'GET') return json({error:'GET only'},405);
  if (url.pathname === '/api/session') return json({auth_enabled:authEnabled,authenticated:true});
  if (url.pathname === '/api/summary') return json({total:0,by_kind:{},by_status:{},by_server:{},categories:[],sources:[],scope:{}});
  if (url.pathname === '/api/assets') return json({items:[],total:0,page:1,page_size:30});
  if (url.pathname === '/api/resource-mapping') return json({items:[longResource],groups:[],summary:{records:1,unique_paths:1},baseline:{},generated_at:'2026-11-15T03:00:00Z'});
  if (url.pathname === '/api/ingestion/status') return json({mode:'not-configured',jobs:[]});
  if (url.pathname === '/api/ingestion/published') return json({items:[]});
  if (sourcePaths.includes(req.url)) {
    active++;
    maxActive = Math.max(maxActive,active);
    return setTimeout(() => {
      active--;
      if (scenario === 'all_failed' && !url.pathname.startsWith('/docs/')) return json({error:'Do not include raw server diagnostics '+sentinel},503);
      if (scenario === 'partial' && url.pathname === '/papers/api/export') return json({error:'Do not include raw server diagnostics '+sentinel},503);
      if (scenario === 'guide_failed' && url.pathname === '/docs/agent-guide.md') return text('Private failure '+sentinel,503);
      if (scenario === 'unauthenticated' && url.pathname === '/progress/api/progress-digest') return text('<html><body>Login '+sentinel+'</body></html>',401,'text/html');
      if (scenario === 'login_html' && url.pathname === '/docs/agent-guide.md') return text('<!doctype html><html>Login '+sentinel+'</html>',200,'text/html');
      if (scenario === 'plain_html' && url.pathname === '/docs/agent-guide.md') return text('<!doctype html><html>Login '+sentinel+'</html>');
      if (scenario === 'redirect' && url.pathname === '/papers/api/export') {res.writeHead(302,{Location:'/auth/not-followed'});return res.end();}
      if (scenario === 'forbidden' && url.pathname === '/papers/api/export') return json({error:'denied '+sentinel},403);
      if (url.pathname === '/docs/agent-guide.md') return text(guide);
      if (url.pathname === '/docs/agent-contract.json') return json(contract);
      const stamp = {observed_at:'2026-11-14T15:00:00Z',fixture_source:url.pathname};
      if (url.pathname === '/api/export.json') return json({...stamp,assets:[{id:'stable-1',name:'合成研究资料',token:sentinel,metadata:{apiKey:sentinel,access_token:sentinel,authHeaders:{Authorization:sentinel},nested:[{clientSecret:sentinel,source_id:'original-evidence-1'}],description:'完整研究内容保留。'}}]});
      if (url.pathname === '/api/research-guide') return json({...stamp,categories:[],newcomer_steps:[]});
      if (url.pathname === '/api/platform/library') return json({...stamp,categories:[],items:[]});
      if (url.pathname === '/api/platform/research') return json({...stamp,models:[],research_tracks:[],partners:[],sources:[]});
      if (url.pathname === '/api/workspace-docs') return json({...stamp,items:[]});
      if (url.pathname === '/api/platform/servers') return json({...stamp,mode:'not_configured',servers:[]});
      if (url.pathname === '/progress/api/progress-digest') return json({...stamp,document:null,status:{state:'pending'}});
      if (url.pathname === '/progress/api/lab-review') return json({...stamp,lab:{},topics:[],members:[],project_records:[],sources:[]});
      if (url.pathname === '/progress/api/directions') return json({...stamp,items:[]});
      if (url.pathname === '/progress/api/direction-methods') return json({...stamp,status:'published',directions:[],sources:[]});
      if (url.pathname === '/papers/api/export') return json({...stamp,schema_version:1,papers:[{id:'paper-1',title:'合成论文',notes:'共享笔记保留',source:'library/paper-1/source.pdf'}]});
    },25);
  }
  const shared = /^\/progress\/assets\/(d3\.v7\.min\.js|rhythm\.js|rhythm\.css)$/.exec(url.pathname);
  const filename = shared ? path.resolve(__dirname,'../../research-progress-next/web',shared[1])
    : path.join(staticRoot,url.pathname === '/'?'index.html':url.pathname.slice(1));
  if (!shared && !/^(?:\/|\/(?:index\.html|agent-context\.js|workspace\.js|app\.js|styles\.css|platform-theme\.css|workspace\.css|astronomy\/hubble-(?:640|1024)\.webp))$/.test(url.pathname)) return json({error:'not_found'},404);
  if (!fs.existsSync(filename)) return json({error:'not_found'},404);
  const type = filename.endsWith('.js')?'text/javascript':filename.endsWith('.css')?'text/css':filename.endsWith('.webp')?'image/webp':'text/html; charset=utf-8';
  res.writeHead(200,{'Content-Type':type});
  res.end(fs.readFileSync(filename));
});

async function takeSnapshot(page, keyboard=false) {
  const start = requests.length;
  maxActive = 0;
  const event = page.waitForEvent('download');
  if (keyboard) {await page.locator('#agent-context-download').focus();await page.keyboard.press('Enter');}
  else await page.locator('#agent-context-download').click();
  const download = await event;
  assert.match(download.suggestedFilename(),/^research-context-[\dTZ-]+\.json$/);
  const result = JSON.parse(fs.readFileSync(await download.path(),'utf8'));
  await page.waitForFunction(() => !document.getElementById('agent-context-download').disabled);
  const actual = requests.slice(start);
  assert.deepEqual(actual.map(row=>row.target).sort(),[...sourcePaths].sort(),'download reads exactly the thirteen fixed sources once, including the review query');
  assert.ok(maxActive>1,'independent source reads run concurrently');
  assert.ok(actual.every(row=>row.method==='GET'));
  assert.ok(actual.every(row=>!row.headers.authorization),'no bearer header is acquired or sent');
  return result;
}

async function expectNoSnapshot(page, mode, message) {
  scenario = mode;
  let downloads = 0;
  const onDownload = () => downloads++;
  page.on('download',onDownload);
  const start = requests.length;
  await page.locator('#agent-context-download').click();
  await page.waitForFunction(() => !document.getElementById('agent-context-download').disabled);
  assert.match(await page.locator('#agent-context-status').innerText(),message);
  assert.equal(downloads,0,mode+' must not download a false or stale context package');
  assert.equal(requests.slice(start).filter(row=>row.path==='/auth/not-followed').length,0,'authentication redirects are not followed');
  assert.deepEqual(requests.slice(start).map(row=>row.target).sort(),[...sourcePaths].sort());
  page.off('download',onDownload);
}

async function layout(page,width,scale) {
  await page.evaluate(scale=>{
    // Enlarge every actual text style, including existing px rules; changing only
    // the root rem size would miss the portal's fixed-size typography.
    window.agentFontBaseline ||= new Map();
    for (const [node,size] of window.agentFontBaseline) node.style.fontSize=size+'px';
    for (const node of document.querySelectorAll('#agent, #agent *')) {
      if (node instanceof HTMLElement && !window.agentFontBaseline.has(node)) window.agentFontBaseline.set(node,parseFloat(getComputedStyle(node).fontSize));
    }
    for (const [node,size] of window.agentFontBaseline) node.style.fontSize=(size*scale)+'px';
  },scale);
  const bad = await page.locator('#agent').evaluate(section => [...section.querySelectorAll('*')].filter(node => {
    if (!(node instanceof HTMLElement) || !node.getClientRects().length) return false;
    return node.clientWidth>0 && node.scrollWidth>node.clientWidth+1;
  }).map(node=>({tag:node.tagName,id:node.id,class:node.className,w:node.clientWidth,scroll:node.scrollWidth})));
  assert.deepEqual(bad,[],`agent internal overflow ${width}px ${scale*100}%`);
  const resourceOverflow = await page.locator('#resources').evaluate(section => [...section.querySelectorAll('*')].filter(node => {
    if (!(node instanceof HTMLElement) || !node.checkVisibility() || !node.getClientRects().length || node.closest('nav,.sr-only')) return false;
    return node.clientWidth>0 && node.scrollWidth>node.clientWidth+1;
  }).map(node=>({tag:node.tagName,id:node.id,class:node.className,w:node.clientWidth,scroll:node.scrollWidth})));
  assert.deepEqual(resourceOverflow,[],`real long resource content overflow ${width}px`);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`page overflow ${width}px ${scale*100}%`);
  assert.ok(await page.locator('#agent-context-download').evaluate(node=>node.getBoundingClientRect().height>=44));
}

async function main() {
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const base = 'http://127.0.0.1:'+server.address().port;
  const browser = await chromium.launch({headless:true});
  try {
    for (const width of [1440,390,320]) {
      scenario = 'normal';authEnabled = false;
      const context = await browser.newContext({viewport:{width,height:1000},hasTouch:width<600});
      await context.addCookies([{name:'private-session',value:sentinel,url:base}]);
      const page = await context.newPage();
      page.setDefaultTimeout(7000);
      const errors=[];page.on('pageerror',error=>errors.push(error.message));
      await page.goto(base+'/#agent');
      await page.waitForLoadState('networkidle');
      await page.evaluate(sentinel=>localStorage.setItem('private-token',sentinel),sentinel);
      assert.equal(await page.locator('#agent').isVisible(),true);
      await page.locator('.resource-card').waitFor();
      assert.match(await page.locator('.resource-card h3').textContent(),new RegExp(resourceName));
      assert.equal(await page.locator('.resource-path code').textContent(),resourcePath);
      assert.ok(await page.locator('.resource-facts dd, .resource-path code').evaluateAll(nodes=>nodes.every(node=>{
        const style=getComputedStyle(node);return style.whiteSpace==='normal' && style.overflowX==='visible';
      })),'resource facts and paths wrap visibly instead of concealing overflow');
      assert.equal(await page.locator('#agent a[href="/docs/agent-guide.md"]').count(),2);
      assert.equal(await page.locator('#agent a[href="/docs/agent-contract.json"]').count(),1);
      assert.match(await page.locator('#agent').innerText(),/网页与浏览器 Agent 统一使用飞书登录/);
      assert.match(await page.locator('#agent').innerText(),/不需要单独领取平台令牌/);
      assert.match(await page.locator('#agent-code').innerText(),/credentials: "same-origin"/);
      assert.doesNotMatch(await page.locator('#agent-code').innerText(),/开发模式|curl|DATA_CENTER_TOKEN/);
      assert.match(await page.locator('#ingestion-agent-code').textContent(),/已登录的平台页面/);

      const full = await takeSnapshot(page,true);
      assert.equal(full.schema_version,'1.0');assert.equal(full.mode,'offline_snapshot');assert.equal(full.complete,true);
      assert.ok(Number.isFinite(Date.parse(full.generated_at)));
      assert.equal(full.readme,guide);assert.deepEqual(full.contract,contract);
      assert.equal(Object.keys(full.sources).length,13);assert.deepEqual(full.failed_sources,[]);
      assert.ok(Object.values(full.sources).every(source=>source.status==='ok' && Number.isFinite(Date.parse(source.fetched_at))));
      assert.equal(full.sources.lab_review.url,'/progress/api/lab-review?format=json');
      assert.equal(full.sources.direction_methods.url,'/progress/api/direction-methods');
      assert.equal(full.sources.direction_methods.data.status,'published');
      assert.equal(full.sources.catalog.data.assets[0].id,'stable-1');
      assert.equal(full.sources.catalog.data.assets[0].metadata.description,'完整研究内容保留。');
      assert.equal(full.sources.catalog.data.assets[0].metadata.nested[0].source_id,'original-evidence-1');
      assert.equal(full.sources.catalog.data.observed_at,'2026-11-14T15:00:00Z');
      assert.equal(full.sources.literature.data.papers[0].notes,'共享笔记保留');
      assert.doesNotMatch(JSON.stringify(full),new RegExp(sentinel));
      assert.match(await page.locator('#agent-context-status').innerText(),/离线快照/);
      assert.equal(await page.locator('#agent-context-login').isHidden(),true);
      for (const scale of [1,2]) {
        await layout(page,width,scale);
        if (process.env.RESEARCH_DIGEST_SCREENSHOTS) {
          await page.locator('#agent').evaluate(node=>node.scrollIntoView({block:'start',behavior:'instant'}));
          await page.screenshot({path:path.join(process.env.RESEARCH_DIGEST_SCREENSHOTS,`agent-context-${width}-${scale*100}.png`)});
        }
      }
      await layout(page,width,1);
      if (process.env.RESEARCH_DIGEST_SCREENSHOTS) {
        await page.locator('.resource-card').evaluate(node=>node.scrollIntoView({block:'center',behavior:'instant'}));
        await page.screenshot({path:path.join(process.env.RESEARCH_DIGEST_SCREENSHOTS,`resource-long-${width}.png`)});
      }

      scenario = 'partial';
      const partial = await takeSnapshot(page);
      assert.equal(partial.complete,false);assert.deepEqual(partial.failed_sources,['literature']);
      assert.deepEqual(partial.sources.literature.status,'failed');assert.equal(partial.sources.literature.error_code,'http_503');
      assert.equal('data' in partial.sources.literature,false);
      assert.doesNotMatch(JSON.stringify(partial),new RegExp(sentinel));
      assert.match(await page.locator('#agent-context-status').innerText(),/不完整快照/);
      assert.match(await page.locator('#agent-context-failures').innerText(),/文献目录与共享笔记/);
      await layout(page,width,2);
      await layout(page,width,1);

      for (const mode of ['unauthenticated','login_html','plain_html','redirect','forbidden']) {
        await expectNoSnapshot(page,mode,/上下文未导出.*飞书登录/);
        assert.equal(await page.locator('#agent-context-login').isVisible(),true);
        assert.doesNotMatch(await page.locator('#agent-context-failures').innerText(),new RegExp(sentinel));
      }
      await expectNoSnapshot(page,'all_failed',/没有取得可用的研究来源/);
      scenario='guide_failed';
      const withoutGuide=await takeSnapshot(page);
      assert.equal(withoutGuide.readme,null);assert.equal(withoutGuide.complete,false);
      assert.deepEqual(withoutGuide.failed_sources,['guide']);
      scenario='normal';
      assert.equal((await takeSnapshot(page)).complete,true,'recovery produces a fresh full snapshot');
      assert.equal(await page.locator('#agent-context-failures').isHidden(),true);
      assert.equal(await page.locator('#agent-context-login').isHidden(),true);
      assert.deepEqual(errors,[]);
      await context.close();
      console.log(`PASS ${width}px: fixed GET-only snapshot, no credentials, partial failures, 401/HTML/redirect rejection, fresh recovery, keyboard, 100/200% reflow and real long resource/path`);
    }
    authEnabled=true;scenario='normal';
    const page=await browser.newPage();
    await page.goto(base+'/#agent');await page.waitForLoadState('networkidle');
    assert.match(await page.locator('#agent-code').innerText(),/目录令牌不能替代飞书登录/);
    assert.doesNotMatch(await page.locator('#agent-code').innerText(),/Bearer|curl/);
    assert.ok(requests.every(row=>row.method==='GET'),'entire regression is read-only');
    assert.ok(!requests.some(row=>/\/(?:settings|state)(?:\?|$)|\.pdf$|report-source/.test(row.path)),'never reads account configuration or originals');
    await page.close();
  } finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
}
main().catch(error=>{console.error(error);process.exitCode=1;server.close();});
