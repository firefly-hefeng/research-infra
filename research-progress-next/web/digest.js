'use strict';

// This view follows teamActivity's visible-page refresh cycle. It never rewrites forms.
const progressDigest = (() => {
  const $ = id => document.getElementById(id);
  const labels = {done:'进展', results:'成果与证据', blockers:'阻塞与待确认', next:'下一步'};
  const briefLabels = {overview:'总体定位', findings:'关键发现', constraints:'关键约束', priorities:'优先行动'};
  const sourceLabels = {daily:'日报原文', weekly:'周报原文', direction:'方向文书'};
  let active = false, epoch = 0, snapshot, hasDocument = false;

  function element(tag, text, className) {
    const result = document.createElement(tag);
    if (text !== undefined && text !== null) result.textContent = text;
    if (className) result.className = className;
    return result;
  }

  function dateLabel(value) {
    if (!value) return '';
    if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
    const parsed = new Date(value);
    if (!Number.isFinite(parsed.getTime())) return '';
    return new Intl.DateTimeFormat('zh-CN', {
      timeZone:'Asia/Shanghai', year:'numeric', month:'2-digit', day:'2-digit',
      hour:'2-digit', minute:'2-digit', hour12:false,
    }).format(parsed);
  }

  function sourceUrl(value, original = false) {
    if (typeof value !== 'string' || !value) return null;
    try {
      const url = new URL(value, location.href);
      if (url.origin !== location.origin || !['http:', 'https:'].includes(url.protocol)) return null;
      if (original) {
        if (!/^\/(?:progress\/)?api\/report-source\//.test(url.pathname)) return null;
        // A relative path also works when the progress app runs without the portal prefix.
        return 'api/report-source/' + url.pathname.split('/api/report-source/')[1] + url.search;
      }
      if (/^\/(?:progress\/)?$/.test(url.pathname) && /^#(?:team|directions)(?:\?|$)/.test(url.hash)) return url.hash;
      return null;
    } catch { return null; }
  }

  function disclosure(key, summaryText, className) {
    const details = element('details', undefined, className);
    details.dataset.digestKey = key;
    details.append(element('summary', summaryText));
    return details;
  }

  function itemSources(item, sources, key) {
    const refs = [...new Set(Array.isArray(item.source_ids) ? item.source_ids : [])]
      .map(id => sources.get(id)).filter(Boolean);
    if (!refs.length) return null;
    const details = disclosure(key, `查看依据 · ${refs.length} 份来源`, 'digest-sources');
    const list = element('ol');
    for (const source of refs) {
      const row = element('li');
      const href = sourceUrl(source.url);
      const label = sourceLabels[source.kind] || '来源记录';
      const title = source.title ? `${label} · ${source.title}` : label;
      const link = element(href ? 'a' : 'span', title);
      if (href) link.href = href;
      row.append(link);
      const original = sourceUrl(source.original_url, true);
      if (original) {
        const download = element('a', source.original_label || '原始文件', 'digest-original');
        download.href = original;
        download.setAttribute('download', '');
        row.append(download);
      }
      for (const attachment of (Array.isArray(source.attachments) ? source.attachments : [])) {
        const attachmentUrl = sourceUrl(attachment.url, true);
        if (!attachmentUrl) continue;
        const download = element('a', '附件 · ' + attachment.name, 'digest-original');
        download.href = attachmentUrl;
        download.setAttribute('download', '');
        row.append(download);
      }
      for (const evidence of (Array.isArray(item.evidence) ? item.evidence : [])) {
        if (evidence.source_id === source.id && evidence.quote) row.append(element('blockquote', evidence.quote));
      }
      list.append(row);
    }
    details.append(list);
    return details;
  }

  function fields(entity, sources, key) {
    const group = element('div', undefined, 'digest-fields');
    for (const [field, label] of Object.entries(labels)) {
      const section = element('section', undefined, 'digest-field');
      section.append(element('h4', label));
      const items = Array.isArray(entity[field]) ? entity[field] : [];
      if (!items.length) section.append(element('p', '近期记录未说明此项。', 'muted'));
      else {
        const list = element('ul');
        items.forEach((item, index) => {
          const row = element('li');
          row.append(element('span', item.text));
          const refs = itemSources(item, sources, `${key}:${field}:${index}`);
          if (refs) row.append(refs);
          list.append(row);
        });
        section.append(list);
      }
      group.append(section);
    }
    return group;
  }

  function baseline(entry) {
    const source = entry.baseline;
    if (!source || ![source.question, source.progress, source.next].some(Boolean)) return null;
    const details = disclosure('baseline:' + entry.id, '已有研究脉络与方向文书', 'digest-baseline');
    details.append(element('p', source.updated_at ? `原文核对于 ${source.updated_at}，与近期报告分开呈现。` : '原文核对日期待补充，与近期报告分开呈现。'));
    for (const [field, title] of [['question','研究问题'], ['progress','已有基础'], ['next','原定下一步']]) {
      if (source[field]) details.append(element('p', `${title} · ${source[field]}`));
    }
    const href = sourceUrl(source.url || '#directions?' + new URLSearchParams({item:entry.id}));
    if (href) {
      const link = element('a', '阅读方向文书 ↗');
      link.href = href;
      details.append(link);
    }
    return details;
  }

  function preview(entry) {
    for (const [field, label] of Object.entries(labels)) {
      const text = entry[field]?.[0]?.text;
      if (text) return `${label} · ${text.length > 100 ? text.slice(0, 99) + '…' : text}`;
    }
    return null;
  }

  function entity(entry, kind, sources) {
    const key = kind + ':' + entry.id;
    const details = disclosure(key, undefined, 'digest-entity');
    const summary = details.firstElementChild;
    summary.append(element('strong', kind === 'member' ? entry.name : entry.title));
    const count = Number(entry.report_count) || 0;
    let meta = count ? `${count} 份关联报告` : '近 28 天暂无关联记录';
    if (kind === 'member') {
      meta = count ? `${count} 份报告` : '近 28 天暂无报告';
      const last = dateLabel(entry.last_report_at);
      if (count && last) meta += ` · 最近 ${last}`;
    }
    summary.append(element('span', meta));
    const excerpt = preview(entry);
    if (excerpt) summary.append(element('span', excerpt, 'digest-preview'));
    const body = element('div', undefined, 'digest-entity-content');
    if (count || excerpt) body.append(fields(entry, sources, key));
    else body.append(element('p', '当前展示范围内没有可归纳的报告，可从下方查阅历史日报与周报。', 'muted'));
    if (kind === 'direction') {
      const previous = baseline(entry);
      if (previous) body.append(previous);
    }
    details.append(body);
    return details;
  }

  function section(title) {
    const block = element('section', undefined, 'digest-section');
    block.append(element('h3', title));
    return block;
  }

  function researchBrief(doc, sources) {
    const asItems = value => Array.isArray(value) ? value : value?.text ? [value] : [];
    const hasBrief = Object.keys(briefLabels).some(key => asItems(doc.research_brief?.[key]).length);
    const root = element('div', undefined, 'digest-brief');
    root.dataset.briefMode = hasBrief ? 'research' : 'records';
    for (const [index,[key,label]] of Object.entries(briefLabels).entries()) {
      const items = hasBrief ? asItems(doc.research_brief[key]) : asItems(doc.team?.[Object.keys(labels)[index]]);
      const block = element('section', undefined, 'digest-brief-field');
      block.append(element('h3', label));
      if (!items.length) block.append(element('p', '现有记录不足以支持判断。', 'muted'));
      items.forEach((item,itemIndex) => {
        block.append(element('p', item.text, 'digest-statement'));
        const evidence = itemSources(item, sources, `brief:${key}:${itemIndex}`);
        if (evidence) block.append(evidence);
      });
      root.append(block);
    }
    if (!hasBrief) root.append(element('p', '当前按已有报告摘要展示；研究主线与优先级判断将随新整理补充。', 'digest-brief-note muted'));
    return root;
  }

  function render(doc) {
    const root = $('digest-content');
    const directionRoot = $('digest-directions');
    const roots = [root,directionRoot];
    const expanded = new Set(roots.flatMap(scope => [...scope.querySelectorAll('details[open][data-digest-key]')].map(item => item.dataset.digestKey)));
    const focused = roots.some(scope => scope.contains(document.activeElement)) ? {
      key:document.activeElement.closest('[data-digest-key]')?.dataset.digestKey,
      href:document.activeElement.getAttribute('href'),
      summary:document.activeElement.tagName === 'SUMMARY',
    } : null;
    const sources = new Map((doc.sources || []).map(source => [source.id, source]));
    const fragment = document.createDocumentFragment();
    fragment.append(researchBrief(doc,sources));
    const counts = doc.counts || {};
    const coverage = element('div', undefined, 'digest-counts');
    coverage.append(element('span', `${counts.members ?? doc.members?.length ?? 0} 位成员 · ${counts.active_members ?? 0} 位有记录`));
    coverage.append(element('span', `${counts.daily ?? 0} 份日报 · ${counts.weekly ?? 0} 份周报`));
    coverage.append(element('span', `${counts.directions ?? doc.directions?.length ?? 0} 个研究方向`));
    fragment.append(coverage);
    if (Object.keys(labels).some(key => doc.team?.[key]?.length)) {
      const full = disclosure('team', '近期记录摘要与依据', 'digest-more');
      full.append(fields(doc.team, sources, 'team'));
      fragment.append(full);
    }
    const rhythm = disclosure('rhythm', '查看日报与周报的记录节律', 'digest-more digest-rhythm');
    const rhythmBody = element('div');
    rhythm.append(rhythmBody);
    rhythm.addEventListener('toggle', () => {
      if (rhythm.open) window.renderReportRhythm?.(rhythmBody,doc,{progressBase:'.'});
    });
    fragment.append(rhythm);
    const directionGrid = element('div', undefined, 'digest-grid');
    for (const entry of doc.directions || []) directionGrid.append(entity(entry, 'direction', sources));
    if (!directionGrid.children.length) directionGrid.append(element('p', '暂未读取到研究方向文书。', 'muted'));
    directionRoot.replaceChildren(directionGrid);
    if (Object.keys(labels).some(key => doc.unassigned?.[key]?.length)) {
      const pending = disclosure('unassigned', '待归类工作', 'digest-more');
      pending.append(element('p', '这些记录暂未关联到已有研究方向，保留原始归属与依据。', 'muted'), fields(doc.unassigned, sources, 'unassigned'));
      directionRoot.append(pending);
    }
    const members = section('全员进展');
    const memberGrid = element('div', undefined, 'digest-grid');
    for (const entry of doc.members || []) memberGrid.append(entity(entry, 'member', sources));
    if (!memberGrid.children.length) memberGrid.append(element('p', '暂未读取到成员名单。', 'muted'));
    members.append(memberGrid);
    fragment.append(members);
    root.replaceChildren(fragment);
    for (const item of roots.flatMap(scope => [...scope.querySelectorAll('details[data-digest-key]')])) {
      if (expanded.has(item.dataset.digestKey)) item.open = true;
    }
    if (focused) {
      const scope = roots.flatMap(scope => [...scope.querySelectorAll('[data-digest-key]')]).find(item => item.dataset.digestKey === focused.key);
      const target = focused.summary ? scope?.firstElementChild : [...(scope || root).querySelectorAll('a')].find(link => link.getAttribute('href') === focused.href);
      target?.focus({preventScroll:true});
    }
    const from = dateLabel(doc.period?.from), to = dateLabel(doc.period?.to);
    $('digest-period').textContent = from && to ? `${from} 至 ${to} · 近 ${doc.period.days || 28} 天的报告` : '近期日报、周报与研究方向';
    hasDocument = true;
  }

  function renderStatus(status, doc) {
    const root = $('digest-status');
    const state = status?.state || 'pending';
    root.dataset.state = state;
    const last = dateLabel(doc?.generated_at || status?.last_success_at);
    const provenance = [doc?.engine,last ? `最近整理 ${last}。` : ''].filter(Boolean).join(' · ');
    const messages = {
      ready:'依据报告与方向文书整理；展开条目可查阅来源。',
      running:hasDocument ? '新记录正在整理，当前保留上次结果。' : '正在整理首次研究全景，请稍后查看。',
      pending:hasDocument ? '新记录等待整理，当前保留上次结果。' : '首次进展等待整理；原始报告可在下方查阅。',
      failed:hasDocument ? '本次整理失败，当前保留上次结果。稍后会自动重试。' : '本次整理失败，稍后会自动重试。原始报告仍可查阅。',
      stale:'有新记录尚未整理，当前保留上次结果。',
      disabled:'自动整理尚未启用。原始日报、周报和方向文书仍可查阅。',
    };
    root.textContent = [provenance, messages[state] || messages.pending].filter(Boolean).join(' ');
  }

  async function refresh() {
    if (!active) return;
    const request = ++epoch;
    try {
      const payload = await api('/api/progress-digest');
      if (!active || request !== epoch) return;
      const doc = payload.document;
      const reviewLink = $('lab-review-link');
      if (reviewLink) reviewLink.hidden = payload.has_lab_review !== true;
      if (doc) {
        const fingerprint = JSON.stringify(doc);
        if (fingerprint !== snapshot) {
          render(doc);
          snapshot = fingerprint;
        }
      } else if (hasDocument) {
        $('digest-content').replaceChildren(element('p', '原始日报、周报和方向文书可在下方查阅。', 'muted'));
        $('digest-directions').replaceChildren();
        $('digest-period').textContent = '';
        snapshot = null;
        hasDocument = false;
      }
      renderStatus(payload.status, doc);
    } catch (error) {
      if (!active || request !== epoch) return;
      const root = $('digest-status');
      root.dataset.state = 'failed';
      root.textContent = hasDocument ? '进展读取失败，保留上次结果。稍后会自动重试。' : '进展暂未读取成功。可先查阅下方原始报告，稍后会自动重试。';
    }
  }

  function start() { active = true; return refresh(); }
  function stop() { active = false; epoch++; }
  $('digest-refresh').onclick = refresh;
  return {start, stop, refresh};
})();
