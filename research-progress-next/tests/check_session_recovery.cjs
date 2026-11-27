/* Run with Node and Playwright available locally. Uses synthetic HTTP responses only. */
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.RESEARCH_PLAYWRIGHT_MODULE || 'playwright');

const webRoot = path.resolve(__dirname, '../web');
let authenticated = false;
let submissions = 0;
let accepted = 0;
let loginVisits = 0;
let roster = [{id: 'alice', name: '甲同学'}, {id: 'bob', name: '乙同学'}];

const server = http.createServer((request, response) => {
  const url = new URL(request.url, 'http://127.0.0.1');
  const json = (status, payload) => {
    response.writeHead(status, {'Content-Type': 'application/json', 'Cache-Control': 'no-store'});
    response.end(JSON.stringify(payload));
  };
  if (url.pathname === '/auth/login') {
    authenticated = true;
    loginVisits++;
    response.writeHead(200, {'Content-Type': 'text/html'});
    response.end('<p>Synthetic login completed</p>');
    return;
  }
  if (url.pathname.startsWith('/progress/api/')) {
    if (request.method === 'POST') submissions++;
    if (!authenticated) {
      json(401, {error: 'feishu_login_required', login_url: 'https://untrusted.invalid/login'});
      return;
    }
    if (url.pathname === '/progress/api/public') {
      json(200, {team_name: '合成登录恢复测试', members: roster,
        week: '2026-W46', date: '2026-11-13', timezone: 'Asia/Shanghai',
        max_upload_bytes: 20971520, max_report_bytes: 65536,
        daily_team_sharing: true, max_daily_attachments: 8, max_daily_attachment_bytes: 20971520});
      return;
    }
    if (url.pathname === '/progress/api/daily/uploads') {
      accepted++;
      json(201, {member_id: 'alice', date: '2026-11-12', week: '2026-W46',
        attachment_count: 2, team_visible: true});
      return;
    }
    if (url.pathname === '/progress/api/uploads') {
      accepted++;
      json(201, {member_id: 'alice', week: '2026-W46', summary_status: 'ready', status_detail: 'Synthetic weekly accepted'});
      return;
    }
    json(404, {error: 'Synthetic endpoint not defined'});
    return;
  }
  const filename = url.pathname === '/progress/' ? 'index.html'
    : /^\/progress\/assets\/(app\.js|activity\.js|digest\.js|rhythm\.js|d3\.v7\.min\.js|style\.css|activity\.css|digest\.css|rhythm\.css)$/.exec(url.pathname)?.[1];
  if (!filename) {
    response.writeHead(404);
    response.end();
    return;
  }
  const type = filename.endsWith('.css') ? 'text/css' : filename.endsWith('.js') ? 'text/javascript' : 'text/html';
  response.writeHead(200, {'Content-Type': type + '; charset=utf-8'});
  response.end(fs.readFileSync(path.join(webRoot, filename)));
});

async function main() {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = 'http://127.0.0.1:' + server.address().port;
  const browser = await chromium.launch({headless: true});
  try {
    for (const width of [1440, 390, 320]) {
      authenticated = false;
      submissions = accepted = loginVisits = 0;
      roster = [{id: 'alice', name: '甲同学'}, {id: 'bob', name: '乙同学'}];
      const page = await browser.newPage({viewport: {width, height: 950}, hasTouch: width < 600});
      page.setDefaultTimeout(5000);
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      const unsaved = () => page.evaluate(() => {
        const event = new Event('beforeunload', {cancelable: true});
        window.dispatchEvent(event);
        return event.defaultPrevented;
      });
      await page.goto(base + '/progress/#daily');
      const banner = page.locator('#session-recovery');
      await banner.waitFor({state: 'visible'});
      assert.match(await banner.innerText(), /请重新登录飞书/);
      const login = page.locator('#session-login');
      const target = new URL(await login.getAttribute('href'));
      assert.equal(target.origin, base);
      assert.equal(target.pathname, '/auth/login');
      assert.equal(target.searchParams.get('return_to'), '/progress/#daily');
      assert.equal(await login.getAttribute('target'), '_blank');
      assert.equal(await login.getAttribute('rel'), 'noopener');

      async function loginAndResume() {
        const popup = page.waitForEvent('popup');
        await login.click();
        const child = await popup;
        await child.waitForLoadState();
        assert.equal(new URL(child.url()).origin, base);
        await child.close();
        await page.getByRole('button', {name: '已登录，继续编辑'}).click();
        await banner.waitFor({state: 'hidden'});
      }

      await loginAndResume();
      await page.locator('#daily-member').selectOption('alice');
      await page.locator('#daily-date').fill('2026-11-12');
      for (const key of ['done', 'results', 'blockers', 'next']) {
        await page.locator('#daily-field-' + key).fill('合成草稿 ' + key);
      }
      await page.locator('#daily-attachments').setInputFiles([{name: 'evidence.txt', mimeType: 'text/plain', buffer: Buffer.from('synthetic evidence')}, {name:'results.csv',mimeType:'text/csv',buffer:Buffer.from('condition,value\nsynthetic,1')}]);
      await page.locator('#report-file').setInputFiles({name: 'weekly.txt', mimeType: 'text/plain', buffer: Buffer.from('synthetic weekly')});
      const rawBody = '# 甲同学 · 2026-11-12 科研日报\n\n## 今日完成\n合成正文\n\n## 结果与证据\n合成结果\n\n## 问题与阻塞\n未说明\n\n## 明日计划\n继续检验\n';
      await page.locator('#daily-file').setInputFiles({name: 'daily.md', mimeType: 'text/markdown', buffer: Buffer.from(rawBody)});
      authenticated = false;
      await page.getByRole('button', {name: '保存日报', exact: true}).click();
      await banner.waitFor({state: 'visible'});
      await page.locator('#daily-feedback').getByText(/飞书登录已过期/).waitFor();
      assert.equal(submissions, 1);
      assert.equal(accepted, 0);
      assert.equal(await page.locator('#daily-field-done').inputValue(), '合成草稿 done');
      assert.equal(await unsaved(), true);
      assert.equal(await page.evaluate(() => localStorage.getItem('research-progress:last-submitted-member')), null);
      await page.getByRole('button', {name: '已登录，继续编辑'}).click();
      await page.locator('#session-recovery-message').getByText(/飞书登录已过期/).waitFor();
      await loginAndResume();
      assert.equal(await page.locator('#daily-member').inputValue(), 'alice');
      assert.equal(await page.locator('#daily-date').inputValue(), '2026-11-12');
      assert.equal(await page.locator('#daily-field-done').inputValue(), '合成草稿 done');
      for (const [id, name] of [['daily-attachments', 'evidence.txt'], ['daily-file', 'daily.md'], ['report-file', 'weekly.txt']]) {
        assert.equal(await page.locator('#' + id).evaluate(input => input.files[0].name), name);
      }
      assert.equal(await page.locator('#daily-attachments').evaluate(input=>input.files.length),2);
      assert.equal(submissions, 1);
      assert.equal(loginVisits, 2);
      await page.getByRole('button', {name: '保存日报', exact: true}).click();
      await page.locator('#daily-feedback').getByText(/日报保存成功/).waitFor();
      assert.equal(submissions, 2);
      assert.equal(accepted, 1);
      assert.equal(await page.evaluate(() => localStorage.getItem('research-progress:last-submitted-member')), 'alice');
      // A different, unsubmitted weekly report still warrants a warning.
      assert.equal(await unsaved(), true);
      await page.getByRole('navigation', {name: '科研进度导航'}).getByRole('link', {name: '提交周报'}).click();
      await page.locator('#member').selectOption('alice');
      await page.getByRole('button', {name: '上传周报', exact: true}).click();
      await page.locator('#upload-feedback').getByText(/周报提交成功/).waitFor();
      assert.equal(await unsaved(), false);
      await page.getByRole('navigation', {name: '科研进度导航'}).getByRole('link', {name: '提交日报'}).click();
      await page.locator('#daily-field-done').fill('修改后的草稿');
      assert.equal(await unsaved(), true);
      await page.locator('#daily-field-done').fill('合成草稿 done');
      assert.equal(await unsaved(), false);
      // A successful form retains its text and files during safe navigation.
      await page.reload();
      await page.waitForFunction(() => document.getElementById('daily-member').value === 'alice');
      assert.equal(await page.locator('#member').inputValue(), 'alice');
      assert.equal(await unsaved(), false);
      // An existing deliberate selection wins over the remembered member on initialization.
      await page.locator('#daily-member').selectOption('bob');
      authenticated = false;
      await page.getByRole('button', {name: '下载模板 ↓', exact: true}).click();
      await banner.waitFor({state: 'visible'});
      await loginAndResume();
      assert.equal(await page.locator('#daily-member').inputValue(), 'bob');
      roster = [{id: 'bob', name: '乙同学'}];
      await page.reload();
      await page.waitForFunction(() => document.getElementById('daily-member').options.length === 2);
      assert.equal(await page.locator('#daily-member').inputValue(), '');
      assert.equal(await page.locator('#member').inputValue(), '');
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      assert.deepEqual(errors, []);
      await page.close();
      console.log(width + 'px session recovery, saved drafts, unsaved changes and roster-aware member preference passed');
    }
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => server.close());
