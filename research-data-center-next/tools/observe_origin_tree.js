// Read only the open research navigation tree. The caller supplies already curated section IDs.
async (scope) => {
  const pause = (ms) => new Promise(resolve => setTimeout(resolve, ms));
  const rowSelector = '#TOC-ROOT [data-node-uid][data-node-pos]';
  const token = row => new URLSearchParams(row.dataset.nodeUid).get('wikiToken');
  const title = row => row.querySelector('.workspace-tree-view-node-content')?.innerText.trim();
  const rowFor = id => [...document.querySelectorAll(rowSelector)].find(row => token(row) === id);
  if (location.origin !== scope.origin || location.pathname !== '/wiki/' + scope.root) {
    throw Error('Open the signed-in research root in the selected tab');
  }
  const initial = document.querySelector('#TOC-ROOT')?.closest('.workspace-scroll-area');
  if (initial) initial.scrollTop = 0;
  for (let n = 0; n < 30 && !rowFor(scope.root); n++) await pause(200);
  const scroller = document.querySelector('#TOC-ROOT')?.closest('.workspace-scroll-area');
  if (!scroller || !rowFor(scope.root)) throw Error('Research navigation unavailable to this session');

  async function sweep(visit) {
    scroller.scrollTop = 0;
    for (let step = 0; step < 120; step++) {
      await pause(90);
      for (const row of document.querySelectorAll(rowSelector)) visit(row);
      const end = scroller.scrollHeight - scroller.clientHeight;
      if (scroller.scrollTop >= end - 2) return;
      scroller.scrollTop = Math.min(end, scroller.scrollTop + Math.max(100, scroller.clientHeight / 2));
    }
    throw Error('Research navigation exceeded the bounded scan');
  }

  const sections = {};
  for (const id of scope.sections) {
    let parentOffset, position;
    await sweep(row => {
      if (token(row) === id) { parentOffset = scroller.scrollTop; position = row.dataset.nodePos; }
    });
    if (parentOffset !== undefined) { scroller.scrollTop = parentOffset; await pause(100); }
    const parent = rowFor(id);
    if (!parent || !parent.isConnected || !title(parent)) {
      sections[id] = {status: 'not_observed'};
      continue;
    }
    const parentTitle = title(parent);
    const control = parent.querySelector('.workspace-tree-view-node-expand-arrow--collapsed [role=button]');
    if (control) { control.click(); await pause(400); }
    const entries = new Map(), expandable = new Set();
    const collect = row => {
      const pos = row.dataset.nodePos;
      if (!pos.startsWith(position + ',') || pos.split(',').length !== position.split(',').length + 1) return;
      const key = token(row), label = title(row);
      if (!key || !/^[a-zA-Z0-9]+$/.test(key) || !label) throw Error('Unrecognized child in navigation');
      entries.set(key, label);
      if (row.querySelector('.workspace-tree-view-node-expand-arrow [role=button]')) expandable.add(key);
    };
    let previous = '', stable = false;
    for (let n = 0; n < 6; n++) {
      entries.clear();
      expandable.clear();
      await sweep(collect);
      const signature = JSON.stringify([...entries.entries()].sort());
      if (n && entries.size && signature === previous) { stable = true; break; }
      previous = signature;
      await pause(200);
    }
    sections[id] = {status: stable ? 'observed' : 'incomplete', title: parentTitle,
                    children: Object.fromEntries(entries), expandable_children: [...expandable]};
    if (control && id !== scope.root && !scope.keepExpanded) {
      rowFor(id)?.querySelector('.workspace-tree-view-node-expand-arrow--expanded [role=button]')?.click();
      await pause(100);
    }
  }
  return sections;
}
