'use strict';

// A shared D3 view of report records. Counts describe the archive, never research completion.
window.renderReportRhythm = function (container, doc, options = {}) {
  container.replaceChildren();
  container.classList.add('report-rhythm');
  const d3 = window.d3;
  const from = doc.period?.from, to = doc.period?.to;
  if (!d3 || !/^\d{4}-\d{2}-\d{2}$/.test(from || '') || !/^\d{4}-\d{2}-\d{2}$/.test(to || '')) {
    const message = document.createElement('p');
    message.textContent = '记录节律暂不可绘制。报告日期和原文仍可从日报、周报查阅。';
    container.append(message);
    return;
  }
  const start = new Date(from + 'T00:00:00Z'), end = new Date(to + 'T00:00:00Z');
  const days = d3.utcDay.range(start, d3.utcDay.offset(end, 1));
  if (!days.length || days.length > 366) return;
  const isoDate = date => date.toISOString().slice(0,10);
  const isoWeek = date => {
    const thursday = new Date(date);
    thursday.setUTCDate(thursday.getUTCDate() + 3 - (thursday.getUTCDay() + 6) % 7);
    const year = thursday.getUTCFullYear();
    const week = Math.ceil((thursday - new Date(Date.UTC(year, 0, 1)) + 86400000) / 604800000);
    return `${year}-W${String(week).padStart(2,'0')}`;
  };
  const dates = days.map(isoDate);
  const weeks = [...new Set(days.map(isoWeek))];
  const sources = [...new Map((doc.sources || []).filter(source => source?.id).map(source => [source.id,source])).values()];
  const base = options.progressBase === '.' ? '' : '/progress/';
  const route = (week,date) => base + '#team?' + new URLSearchParams({week,...(date ? {date} : {})});
  const sourceRoute = source => {
    try {
      const url = new URL(source.url,location.origin+'/progress/');
      if (url.origin !== location.origin || !/^\/(?:progress\/)?$/.test(url.pathname) || !/^#team\?/.test(url.hash)) return null;
      const query = new URLSearchParams(url.hash.split('?')[1]);
      if (!query.has('member') || !(query.has('date') || query.get('report') === 'weekly')) return null;
      return base + url.hash;
    } catch { return null; }
  };

  for (const [kind,title,keys] of [['daily','日报 · 按日',dates],['weekly','周报 · 按周',weeks]]) {
    const records = sources.filter(source => source.kind === kind);
    const rows = keys.map(key => {
      const matches = records.filter(source => (kind === 'daily' ? source.date : source.week) === key);
      return {key,count:matches.length,sources:matches};
    });
    const total = d3.sum(rows,row => row.count);
    const figure = document.createElement('figure');
    figure.className = 'report-rhythm-figure';
    figure.dataset.rhythmKind = kind;
    const caption = document.createElement('figcaption');
    const heading = document.createElement('strong');
    heading.textContent = title;
    const count = document.createElement('span');
    count.textContent = `${total} 份可追溯记录`;
    caption.append(heading,count);
    figure.append(caption);
    container.append(figure);
    const width = Math.max(240, Math.min(640, Math.round(figure.getBoundingClientRect().width) || 360));
    const height = 132, margin = {top:22,right:12,bottom:27,left:24};
    const x = d3.scaleBand().domain(keys).range([margin.left,width-margin.right]).padding(kind === 'daily' ? .3 : .56);
    const maximum = Math.max(1,d3.max(rows,row => row.count));
    const y = d3.scaleLinear().domain([0,maximum]).nice().range([height-margin.bottom,margin.top]);
    const svg = d3.select(figure).append('svg').attr('viewBox',`0 0 ${width} ${height}`)
      .attr('role','img').attr('aria-label',`${title}，${from}至${to}，${total}份报告记录。数量不代表科研完成度。`);
    svg.append('text').attr('class','report-rhythm-unit').attr('x',margin.left).attr('y',12).text('份');
    svg.append('g').attr('class','report-rhythm-y').attr('transform',`translate(${margin.left},0)`)
      .call(d3.axisLeft(y).tickValues([...new Set([0,maximum])]).tickFormat(d3.format('d')).tickSize(0))
      .call(axis => axis.select('.domain').remove());
    svg.append('line').attr('class','report-rhythm-baseline').attr('x1',margin.left).attr('x2',width-margin.right)
      .attr('y1',y(0)).attr('y2',y(0));
    const tickValues = kind === 'daily' ? [...new Set([keys[0],keys[Math.floor((keys.length-1)/2)],keys[keys.length-1]])] : keys;
    svg.append('g').attr('class','report-rhythm-x').attr('transform',`translate(0,${height-margin.bottom})`)
      .call(d3.axisBottom(x).tickValues(tickValues).tickFormat(key => kind === 'daily' ? key.slice(5) : key.slice(5)).tickSize(0).tickPadding(10))
      .call(axis => axis.select('.domain').remove());
    const bar = svg.selectAll('g.report-rhythm-record').data(rows).join('g').attr('class','report-rhythm-record')
      .attr('data-period',row => row.key).attr('data-count',row => row.count);
    bar.each(function(row) {
      const group = d3.select(this);
      const individual = row.count === 1 ? sourceRoute(row.sources[0]) : null;
      const destination = individual || route(kind === 'daily' ? isoWeek(new Date(row.key+'T00:00:00Z')) : row.key,kind === 'daily' ? row.key : null);
      const action = individual ? '阅读成员原文' : kind === 'daily' ? '查看当日全员记录' : '查看本周阶段记录';
      const mark = row.count ? group.append('a').attr('href',destination)
        .attr('aria-label',`${row.key}，${row.count}份${kind === 'daily' ? '日报' : '周报'}，${action}`) : group;
      mark.append('rect').attr('class',row.count ? 'report-rhythm-bar' : 'report-rhythm-zero')
        .attr('x',x(row.key)).attr('y',row.count ? y(row.count) : y(0)-2).attr('width',x.bandwidth())
        .attr('height',row.count ? y(0)-y(row.count) : 2).append('title').text(`${row.key} · ${row.count}份${kind === 'daily' ? '日报' : '周报'}${row.count ? ' · '+action : ''}`);
    });
    if (!total) {
      svg.append('text').attr('class','report-rhythm-empty').attr('x',(width+margin.left)/2).attr('y',65)
        .attr('text-anchor','middle').text('此范围暂无可追溯记录');
    }
  }
  const note = document.createElement('p');
  note.className = 'report-rhythm-note';
  note.textContent = `${from} 至 ${to} · 按来源档案计数；点有记录的柱查看相应日期或周次。报告数量不代表科研完成度。`;
  container.append(note);
};
