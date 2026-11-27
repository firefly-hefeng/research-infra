"use strict";
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let checks = 0;
const check = value => { assert.ok(value); checks++; };
const source = fs.readFileSync('web/app.js', 'utf8').split("document.addEventListener('click'")[0];
const raw = {id:'a'.repeat(64), filename:'source.pdf', status:'bibliography', card:null,
  available:true, fulltext_available:false, notes:'', favorite:false,
  bibliography:{title:'<script>Existing title</script>', authors:['Alice'], year:2024, doi:'10.5555/Example',
    venue:'Indexed venue', summary:'Previously recorded purpose', category:'Clinical speech',
    tags:['Speech'], review_state:'bibliography_only', fulltext_policy:'restricted',
    provenance:[{label:'Curated index',sha256:'b'.repeat(64),record_id:'A01'}]}};
async function run(pathname) {
  const nodes = new Map();
  const node = id => {
    if(!nodes.has(id)) nodes.set(id,{innerHTML:'',textContent:'',value:'',checked:false,hidden:false,open:false,
      disabled:false,scrollTop:0,classList:{add(){},remove(){},toggle(){}},showModal(){this.open=true}});
    return nodes.get(id);
  };
  const calls=[];
  const ctx={document:{getElementById:node},window:{location:{pathname}},URL,console,
    setTimeout,clearTimeout,setInterval,clearInterval,fetch:async(url)=>{calls.push(url);return {status:200,ok:true,json:async()=>({ok:true})}}};
  vm.createContext(ctx);
  vm.runInContext(source+"\nglobalThis.subject={bibliographyState,renderPapers,openPaper,api,setState:value=>state=value};",ctx);
  const subject=ctx.subject;
  const converted=subject.bibliographyState({papers:[raw],jobs:[],agent:{configured:false},running:false});
  check(converted.papers[0].bibliography_only===true);
  check(raw.card===null);
  check(converted.papers[0].card.evidence.length===0);
  check(converted.papers[0].card.needs_review===true);
  const old={...raw,card:{title:'Validated title'}};
  check(subject.bibliographyState({papers:[old]}).papers[0].card.title==='Validated title');
  subject.setState(converted);
  subject.renderPapers();
  check(node('papers').innerHTML.includes('&lt;script&gt;'));
  check(!node('papers').innerHTML.includes('<script>'));
  check(node('papers').innerHTML.includes('原件限阅'));
  check(!node('papers').innerHTML.includes('待原文核验'));
  for (const query of ['10.5555/example','DOI: 10.5555/EXAMPLE','https://doi.org/10.5555%2FExample?ref=copy#note']) {
    node('search').value = query;
    subject.renderPapers();
    check(node('papers').innerHTML.includes(raw.id));
  }
  for (const query of ['https://doi.org/10.5555%ZZ', 'https://unrelated.example/10.5555/Example']) {
    node('search').value = query;
    subject.renderPapers();
    check(node('papers').innerHTML.includes('没有找到匹配的论文'));
  }
  subject.openPaper(raw.id);
  const html=node('detail-content').innerHTML;
  check(html.includes('索引简介'));
  check(!html.includes('原文摘要'));
  check(html.includes('<h3>主题标签</h3>') && !html.includes('作者关键词'));
  check(html.includes('标题、作者与索引简介来自以下已有文献索引。'));
  check(html.includes('Curated index'));
  check(!html.includes('下载 PDF'));
  check(!html.includes('/api/papers/'));
  check(node('generate-reading').hidden===true);
  check(node('reading-status').textContent === '');
  await subject.api('/api/catalog');
  check(calls[0]===(pathname.startsWith('/papers/')?'/papers/api/catalog':'/api/catalog'));
}
(async()=>{await run('/papers/');await run('/');console.log(`Bibliography UI: ${checks} assertions passed.`)})().catch(error=>{console.error(error);process.exitCode=1});
