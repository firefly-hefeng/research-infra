"use strict";
// The behavioral harness creates mock nodes on demand. Check the actual page too,
// so a missing element or a replaced native dialog cannot silently pass those tests.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const html = fs.readFileSync('web/index.html', 'utf8');
const source = fs.readFileSync('web/app.js', 'utf8');
let checks = 0;
const check = (condition, message) => { assert.ok(condition, message); checks++; };
const elements = [...html.matchAll(/<([a-z][a-z0-9-]*)\b([^>]*\bid="([^"]+)"[^>]*)>/gi)];
const byId = new Map(elements.map(match => [match[3], {tag: match[1], attributes: match[2]}]));
check(byId.size === elements.length, 'HTML element IDs must be unique');
const generated = new Set([...source.matchAll(/\bid="([a-z][a-z0-9-]*)"/g)].map(match => match[1]));
for (const id of new Set([...source.matchAll(/\$\('([^']+)'\)/g)].map(match => match[1]))) {
  check(byId.has(id) || generated.has(id), `Bound node ${id} must exist in HTML or generated reader content`);
}
for (const [id, tag] of Object.entries({'provider-settings': 'dialog', management: 'section', 'provider-fields': 'fieldset', 'provider-form': 'form'})) {
  check(byId.get(id)?.tag === tag, `${id} must retain its native ${tag} behavior`);
}
check(/\bdisabled\b/.test(byId.get('provider-fields').attributes), 'Settings fields start disabled until loading succeeds');
const fieldsetStart = html.indexOf('<fieldset id="provider-fields"');
check(html.indexOf('id="retry-settings"') < fieldsetStart, 'Retry remains outside the fieldset disabled on a load failure');
for (const [name, route] of Object.entries({discover: '#discover', catalog: '#catalog', favorites: '#favorites', workspace: '#workspace'})) {
  const node = byId.get('nav-' + name);
  check(node?.tag === 'a' && node.attributes.includes(`href="${route}"`), `${name} navigation must be a deep link`);
}
for (const id of ['nav-all-count', 'nav-favorite-count', 'nav-pending-count', 'stat-categories', 'catalog-categories', 'catalog-search', 'papers-pagination']) {
  check(byId.has(id), `New module node ${id} must exist`);
}
check(/class="[^"]*\bagent-state\b/.test(html), 'Agent state selector must resolve');
check(/<input\b[^>]*id="api-key"[^>]*type="password"/.test(html), 'API key input must remain masked');
check(!html.includes('onclick='), 'Page events remain in the CSP-compatible external script');
console.log(`UI markup contracts: ${checks} assertions passed.`);
