/* Archived summaries need real member content: padding, reflow, sources and original-report links. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const {chromium} = require(process.env.RESEARCH_PLAYWRIGHT_MODULE || 'playwright');
const web = path.resolve(__dirname,'../web');
const roster = [{id:'alpha',name:'成员甲'},{id:'beta',name:'成员乙'},{id:'gamma',name:'成员丙'}];
const longURL = 'https://example.test/evidence/'+'UnbrokenSourcePath'.repeat(15);
const sourceID = 'source-run-'+'abcdef0123456789'.repeat(16);
const quote = '引用：'+ 'LongUnbrokenReference'.repeat(12)+'，结论的适用范围仍需复核。';
const member = (id,name) => ({id,name,done:['已完成协议核对并保留真实实验记录。'],results:[`完整来源 [${longURL}](${longURL})`,'来源ID '+sourceID],blockers:[quote],next:['复核结束标记：所有原文必须完整保留。'],source_sha256:'abcdef0123456789'.repeat(4)});
const docs = {
  '2026-W45':{week:'2026-W45',date_range:['2026-11-02','2026-11-08'],engine_label:'合成归档回归',generated_at:'2026-11-09T00:00:00Z',submitted:2,received:2,expected:3,
    members:[member('alpha','成员甲'),member('beta','成员乙')],overview:['研究范围：'+longURL],team_risks:['需要协助：'+sourceID],next_actions:[quote],pending:[],missing:[]},
  '2026-W44':{week:'2026-W44',members:[],overview:[],team_risks:[],next_actions:[]},
};
const methods=[];
const server=http.createServer((request,response)=>{
  methods.push(request.method);
  const url=new URL(request.url,'http://127.0.0.1');
  const json=data=>{response.writeHead(200,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});response.end(JSON.stringify(data));};
  if(url.pathname==='/progress/api/public')return json({team_name:'归档成员排版合成回归',members:roster,week:'2026-W46',date:'2026-11-14',timezone:'Asia/Shanghai',max_upload_bytes:20971520,max_report_bytes:65536,daily_team_sharing:true,max_daily_attachments:8,max_daily_attachment_bytes:20971520});
  if(url.pathname==='/progress/api/progress-digest')return json({document:null,status:{state:'disabled'}});
  if(url.pathname==='/progress/api/directions')return json({items:[],unavailable:[]});
  if(url.pathname==='/progress/api/team')return json({items:[{week:'2026-W45',submitted:2,expected:3},{week:'2026-W44',submitted:0,expected:3}]});
  if(/^\/progress\/api\/team\/2026-W(?:44|45)$/.test(url.pathname))return json(docs[url.pathname.split('/').pop()]);
  if(url.pathname==='/progress/api/team/activity') {
    const week=url.searchParams.get('week')||'2026-W46',uid=url.searchParams.get('member');
    const first=new Date(week==='2026-W44'?'2026-10-26T00:00:00Z':week==='2026-W45'?'2026-11-02T00:00:00Z':'2026-11-09T00:00:00Z');
    const dates=Array.from({length:7},(_,index)=>{const day=new Date(first);day.setUTCDate(day.getUTCDate()+index);return day.toISOString().slice(0,10);});
    const fields={done:'成员原始周报正文，保留与归档摘要的区别。',results:longURL,blockers:quote,next:'原文结束标记'};
    const records=week==='2026-W45'?roster.filter(item=>item.id!=='gamma'&&(!uid||item.id===uid)).map(item=>({member_id:item.id,member_name:item.name,week,fields,original_url:'/progress/api/report-source/weekly/'+item.id+'/'+week,original_label:'下载周报原件',attachments:[]})):[];
    return json({week,current_week:'2026-W46',dates,members:roster.map(item=>({...item,days:[],weekly_status:week==='2026-W45'&&item.id!=='gamma'?'published':'missing',weekly_readable:week==='2026-W45'&&item.id!=='gamma'})),weekly_revision:1,daily_records:[],weekly_reports:records,selected_daily:null,selected_weekly:uid&&url.searchParams.get('report')==='weekly'?{fields}:null,weekly_timetable:{weeks:[week],records:[]}});
  }
  let filename=url.pathname==='/progress/'?'index.html':/^\/progress\/assets\/(app\.js|activity\.js|digest\.js|rhythm\.js|d3\.v7\.min\.js|style\.css|activity\.css|digest\.css|rhythm\.css)$/.exec(url.pathname)?.[1];
  if(url.pathname==='/platform-theme.css')filename='../../research-data-center-next/static/platform-theme.css';
  if(url.pathname==='/astronomy/hubble-1024.webp')filename='../../research-data-center-next/static/astronomy/hubble-1024.webp';
  if(!filename){response.writeHead(404);return response.end();}
  response.writeHead(200,{'Content-Type':filename.endsWith('.css')?'text/css':filename.endsWith('.js')?'text/javascript':filename.endsWith('.webp')?'image/webp':'text/html; charset=utf-8'});
  response.end(fs.readFileSync(path.join(web,filename)));
});

async function inspect(page,width,scale,empty=false) {
  const result=await page.evaluate(()=>{
    const panel=document.querySelector('#team-reader .member-panel');
    const heading=panel.querySelector('.panel-heading h2');
    const bounds=panel.getBoundingClientRect();
    const cards=[...panel.querySelectorAll('.member-card')];
    const positions=cards.map(card=>{
      const r=card.getBoundingClientRect(),name=card.querySelector('h3').getBoundingClientRect(),body=card.querySelector('dd').getBoundingClientRect(),source=card.querySelector('.record-source').getBoundingClientRect();
      return {cardLeft:r.left,cardRight:r.right,nameLeft:name.left,bodyLeft:body.left,bodyRight:body.right,sourceLeft:source.left,sourceRight:source.right};
    });
    const empty=panel.querySelector('.empty,.member-grid > p');
    const filter=panel.querySelector('.member-filter');
    const overflow=[...document.querySelectorAll('#team-reader *')].filter(item=>item instanceof HTMLElement&&item.clientWidth>0&&item.getClientRects().length&&getComputedStyle(item).display!=='none'&&item.scrollWidth>item.clientWidth+1).map(item=>({tag:item.tagName,class:item.className,width:item.clientWidth,scroll:item.scrollWidth})).slice(0,10);
    return {panelLeft:bounds.left,panelRight:bounds.right,headingLeft:heading.getBoundingClientRect().left,cards:positions,emptyLeft:empty?empty.getBoundingClientRect().left+parseFloat(getComputedStyle(empty).paddingLeft):null,filter:filter?{left:filter.getBoundingClientRect().left,right:filter.getBoundingClientRect().right}:null,overflow};
  });
  assert.deepEqual(result.overflow,[],`${width}px ${scale*100}% archived report internals overflow`);
  assert.ok(result.headingLeft-result.panelLeft>=16);
  if(empty){assert.ok(result.emptyLeft-result.panelLeft>=16);assert.ok(Math.abs(result.emptyLeft-result.headingLeft)<1.1);}
  else {
    assert.equal(result.cards.length,2);
    assert.ok(Math.abs(result.cards[0].nameLeft-result.headingLeft)<1.1,'heading and first member share a left edge');
    for(const card of result.cards) {
      assert.ok(Math.abs(card.nameLeft-card.bodyLeft)<1.1,'name and body share a left edge');
      assert.ok(card.nameLeft-card.cardLeft>=15.9,'member card has left breathing room');
      assert.ok(card.cardRight-card.bodyRight>=15.9,'member card has right breathing room');
      assert.ok(card.sourceLeft-result.panelLeft>=16&&result.panelRight-card.sourceRight>=16,'source stays inset');
    }
    if(width<=390)assert.ok(Math.abs(result.cards[0].nameLeft-result.cards[1].nameLeft)<1.1,'mobile members use one column');
    else assert.ok(result.cards[1].nameLeft>result.cards[0].nameLeft+100,'desktop members use two columns');
    if(result.filter)assert.ok(result.filter.left-result.panelLeft>=16&&result.panelRight-result.filter.right>=16);
  }
  assert.ok(await page.locator('#team-reader').evaluate(item=>item.getBoundingClientRect().right<=innerWidth+1),`${width}px ${scale*100}% archive exceeds viewport`);
  const outside=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,items:[...document.querySelectorAll('body *')].filter(item=>item instanceof HTMLElement&&item.getClientRects().length&&getComputedStyle(item).display!=='none'&&item.getBoundingClientRect().right>innerWidth+1).map(item=>({tag:item.tagName,id:item.id,class:item.className,right:item.getBoundingClientRect().right})).slice(0,8)}));
  assert.ok(outside.scroll<=outside.width,`${width}px ${scale*100}% root overflow: ${JSON.stringify(outside)}`);
}

async function main(){
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const base='http://127.0.0.1:'+server.address().port,browser=await chromium.launch({headless:true});
  try {
    for(const width of [1440,1057,390,320]) {
      const page=await browser.newPage({viewport:{width,height:1000},hasTouch:width<600});page.setDefaultTimeout(5000);
      const errors=[];page.on('pageerror',error=>errors.push(error.message));
      await page.goto(base+'/progress/#team?week=2026-W45&daily_week=2026-W46&daily_member=beta');
      await page.locator('#team-reader .member-card').last().waitFor({state:'attached'});
      await page.locator('#weekly-archive > summary').click();
      assert.equal(await page.locator('#team-reader .member-card').count(),2);
      assert.match(await page.locator('#team-reader .member-card').first().innerText(),/来源校验 abcdef012345/);
      assert.ok((await page.locator('#team-reader').innerText()).includes(sourceID));
      assert.ok((await page.locator('#team-reader').innerText()).includes('所有原文必须完整保留。'));
      for(const scale of [1,2]) {
        await page.evaluate(scale=>document.documentElement.style.fontSize=(15*scale)+'px',scale);
        await inspect(page,width,scale);
        if(process.env.RESEARCH_DIGEST_SCREENSHOTS)await page.locator('#team-reader').screenshot({path:path.join(process.env.RESEARCH_DIGEST_SCREENSHOTS,`archive-report-${width}-${scale*100}.png`)});
      }
      // Archive links use the existing route, while the independent daily reading scope survives.
      await page.locator('#team-reader .member-report-link').first().click();
      await page.locator('#activity-weekly-list [data-member="alpha"] dd').getByText('成员原始周报正文，保留与归档摘要的区别。',{exact:true}).waitFor();
      assert.match(await page.locator('#daily-week').innerText(),/2026-W46/);
      assert.equal(await page.locator('#daily-member-filter').inputValue(),'beta');
      assert.equal(await page.locator('#activity-weekly-list [data-member="alpha"] a[download]').count(),1);
      await page.evaluate(()=>{location.hash='#team?week=2026-W44&daily_week=2026-W46&daily_member=beta';});
      await page.locator('#team-reader .member-panel > .empty').waitFor({state:'attached'});
      await page.locator('#weekly-archive').evaluate(item=>item.open=true);
      await inspect(page,width,2,true);
      await page.evaluate(()=>{location.hash='#team?week=2026-W45&member=gamma&daily_week=2026-W46&daily_member=beta';});
      await page.locator('#team-reader .member-grid > p').waitFor();
      await inspect(page,width,2,true);
      assert.deepEqual(errors,[]);await page.close();
      console.log(`PASS ${width}px: nonempty archive members, aligned 16px+ insets, two/one columns, long sources, 100/200% reflow, original link and empty states`);
    }
    assert.ok(methods.every(method=>method==='GET'));
  }finally{await browser.close();server.close();}
}
main().catch(error=>{console.error(error);server.close();process.exitCode=1;});
