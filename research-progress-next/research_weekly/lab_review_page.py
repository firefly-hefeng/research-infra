"""Render a reviewed lab snapshot. Originals keep their existing access controls."""
import argparse
from collections import Counter
from functools import lru_cache
from html import escape
import json
from pathlib import Path
from urllib.parse import urlsplit

from .lab_review_json import reading_links


def shared_review(path):
    info = path.stat()
    return _read_shared(path, info.st_ino, info.st_mtime_ns, info.st_size)


@lru_cache(maxsize=2)
def _read_shared(path, inode, modified, size):
    from .core import read_text
    doc = json.loads(read_text(path, 8_000_000))
    if doc.get('audience', 'team') != 'team' or any(
            row.get('kind') == 'project_note' and row.get('audience') != 'team' for row in doc['sources']):
        raise PermissionError
    return doc


def render(doc, embedded_css=None, companion=None):
    def e(value):
        return escape(str(value), quote=True)
    sources = {row['id']:row for row in doc['sources']}
    counts = Counter(row['kind'] for row in sources.values())
    topics, lab_links = reading_links(doc)
    topic_names = {link['key']: row['title'] for link, row in zip(topics, doc['topics'])}
    people = {member['id']: member['name'] for member in doc['members']}

    def related(label, links):
        items = [f'<a href="#{e(anchor)}">{e(title)}</a>' for anchor, title in links]
        return f'<div class="related"><span>{label}</span>{"".join(items)}</div>' if items else ''

    def cite(ref):
        source = sources[ref['id']]
        link = source.get('url', '')
        parsed = urlsplit(link)
        label = e(source['title'])
        if parsed.scheme == 'https' and parsed.netloc == 'rmp.wuwangwo.top' and parsed.path == '/progress/' and parsed.fragment.startswith('team?'):
            label = f'<a href="{e(link)}">{label}</a>'
        return f'<li>{label}<blockquote>{e(ref["quote"])}</blockquote></li>'
    def fields(row, lab=False):
        parts = []
        for key, title in [('progress','本期进展'),('result','结果与证据'),('limit','局限与阻塞'),('next','下一步')]:
            if lab:
                opened = ' open' if key == 'result' or (key == 'progress' and not row['result']) else ''
                parts.append(f'<details class="lab-field"{opened}><summary>{title}<small>{len(row[key])} 项</small></summary>')
            else:
                parts.append(f'<h3>{title}</h3>')
            if not row[key]:
                parts.append('<p class="quiet">本期材料未提供可核对的记录。</p>')
            for i, item in enumerate(row[key]):
                refs = ''.join(cite(ref) for ref in item['evidence'])
                basis = {'reported_plan':'原件所列计划', 'model_suggestion':'复盘建议'}.get(item.get('basis')) if key == 'next' else None
                prefix = f'<strong>{basis}</strong> · ' if basis else ''
                links = related('同段引文见', ((anchor, topic_names[anchor]) for anchor in lab_links[key][i])) if lab else ''
                parts.append(f'<div class="claim"><p>{prefix}{e(item["text"])}</p>{links}<details class="quotes"><summary>核对出处</summary><ul>{refs}</ul></details></div>')
            if lab:
                parts.append('</details>')
        return ''.join(parts)
    def panels(rows, member=False):
        pieces=[]
        for i, row in enumerate(rows):
            title=e(row['name' if member else 'title'])
            if member:
                uid = row['id']
                signed = Counter(x['kind'] for x in sources.values() if x.get('member_id') == uid)
                meta = f'周报 {signed["weekly"]} · 日报 {signed["daily"]}'
                anchor = 'member-' + uid
                crosslinks = related('本人报告被以下问题引用', ((t['key'], topic_names[t['key']]) for t in topics if uid in t['report_member_ids']))
            else:
                anchor = topics[i]['key']
                crosslinks = related('引用署名报告', (('member-' + uid, people[uid]) for uid in topics[i]['report_member_ids']))
                meta='关联已登记方向' if row.get('direction_id') else '由本期材料归纳'
            proof = row.get('direction_evidence') if not member else None
            basis = f'<details class="quotes"><summary>核对正式方向归属</summary><ul>{cite(proof)}</ul></details>' if proof else ''
            pieces.append(f'<details class="panel"><summary>{title}<small>{meta}</small></summary><div id="{e(anchor)}" tabindex="-1">{crosslinks}{basis}{fields(row)}</div></details>')
        return ''.join(pieces)
    project = doc.get('project_records')
    project_nav = '<a href="#projects">项目记录</a>' if project else ''
    project_section = ('<section id="projects"><h2>项目文档中的进展</h2><p class="quiet">文档中的工作按项目归档，个人贡献以具名报告为据。</p>'
                       + fields(project) + '</section>') if project else ''
    period=doc.get('source_window') or {}
    roots=doc['scope'].get('disk_roots', [])
    excluded=doc['scope'].get('skipped_reports',0)
    owners=len({s['member_id'] for s in sources.values() if s.get('member_id') and s['kind'] != 'project_note'})
    if roots:
        read_count = sum(row.get('included', 0) for row in roots)
        disk_scope = f'从 {len(roots)} 个配置目录读取 {read_count} 篇项目材料。'
        for key, label in [('inaccessible','无法读取'),('oversized','超出单篇上限'),('excluded','按范围排除')]:
            n = sum(row.get(key, 0) for row in roots)
            if n:
                disk_scope += f'{label} {n} 篇。'
    elif counts['project_note']:
        disk_scope = '项目文档来自导入的证据清单，本次未重新扫描原目录。'
    else:
        disk_scope = '本版仅使用共享报告，未读取成员项目盘。'
    basis = '个人进展以具名报告为据。' if counts['project_note'] else ''
    css = ('<link rel="stylesheet" href="../assets/lab-review.css">' if embedded_css is None
           else '<style>'+embedded_css+'</style>')
    edition = '人工已校审' if doc.get('editorial_review') else '模型自动整理'
    amendments = doc.get('evidence_corrections', {}).get('claim_count')
    if not doc.get('editorial_review') and type(amendments) is int and amendments > 0:
        edition += f' · 已按原件校订 {amendments} 项'
    companion_link = {'auto':' · <a href="?version=auto">阅读新材料的自动复盘</a>',
                      'reviewed':' · <a href="?version=reviewed">返回人工校审稿</a>'}.get(companion,'')
    lab_claims = sum(len(doc['lab'][key]) for key in ('progress','result','limit','next'))
    lab_topic_links = sum(len(links) for rows in lab_links.values() for links in rows)
    topic_member_links = sum(len(topic['report_member_ids']) for topic in topics)
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>实验室阶段复盘 · 科研平台</title>{css}</head><body><main>
<header><a href="https://rmp.wuwangwo.top/progress/#team">团队进度</a><h1>实验室阶段复盘</h1>
<p>{e(period.get("from","未注明"))} 至 {e(period.get("to","未注明"))} · {e(doc.get("engine",""))} · {edition}{companion_link}</p>
<p>名册 {len(doc["members"])} 人，其中 {owners} 人有本期署名报告。{counts["daily"]} 份日报，{counts["weekly"]} 份周报，{counts["project_note"]} 篇项目记录。报告数仅表示来源覆盖。</p></header>
<section class="reading-guide" aria-labelledby="reading-guide-title"><div class="guide-heading"><h2 id="reading-guide-title">三级金字塔导读</h2><p>逐级追溯；计数只描述本版阅读联系，不作质量或贡献排名。</p></div>
<ol class="pyramid"><li class="pyramid-lab"><span>01 · 结论</span><a href="#lab"><strong>实验室核心结论</strong><small>{lab_claims} 条四栏判断</small></a><p>整体判断与同段引文</p></li>
<li class="pyramid-topics"><span>02 · 主题</span><a href="#topics"><strong>研究主题</strong><small>{len(topics)} 个主题 · {lab_topic_links} 条结论联系</small></a><p>研究问题与方向归属</p></li>
<li class="pyramid-people"><span>03 · 证据</span><a href="#people"><strong>成员证据</strong><small>{owners} / {len(doc["members"])} 人有署名报告 · {topic_member_links} 条主题联系</small></a><p>署名四栏与原报告</p></li></ol></section>
<nav aria-label="报告目录"><a href="#lab">实验室核心结论</a><a href="#topics">研究主题</a><a href="#people">成员证据</a>{project_nav}<a href="#scope">核对范围</a></nav>
<section id="lab"><h2>实验室核心结论</h2>{fields(doc['lab'], lab=True)}</section>
<section id="topics"><h2>按研究主题阅读</h2>{panels(doc['topics'])}</section>
<section id="people"><h2>按成员证据阅读</h2>{panels(doc['members'], True)}</section>{project_section}
<footer id="scope"><h2>核对范围</h2><p>生成时间 {e(doc['generated_at'])}。{disk_scope}排除输入报告 {excluded} 份。{basis}科研结论需结合实验原件复核。不同量纲、数据切分和人群分别解读。</p></footer></main></body></html>'''


if __name__ == '__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('review',type=Path)
    ap.add_argument('output',type=Path)
    args=ap.parse_args()
    css=(Path(__file__).resolve().parents[1]/'web'/'lab-review.css').read_text(encoding='utf-8')
    with args.output.open('x', encoding='utf-8') as stream:
        stream.write(render(json.loads(args.review.read_text(encoding='utf-8')),css))
