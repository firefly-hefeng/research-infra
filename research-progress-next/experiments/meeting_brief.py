"""Build the internal meeting reader beside the approved three-volume review."""
import argparse
from collections import Counter
from datetime import datetime
from hashlib import sha256
from html import escape
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import quote


FIELDS = [('progress', '本期进展'), ('result', '结果与证据'), ('limit', '局限与阻塞'), ('next', '下一步与建议')]


def build(root):
    def read(name):
        return json.loads((root / name).read_bytes())

    lab = read('internal-review-edited.json')
    directions = read('direction-review-edited.json')
    shared = read('team-auto-first-33-corrected.json')
    editorial = read('meeting-decisions.json') if (root / 'meeting-decisions.json').exists() else {}
    cold = read('cold-storage-review.json') if (root / 'cold-storage-review.json').exists() else None
    other = read('other-current-review.json') if (root / 'other-current-review.json').exists() else None
    supplements = [(anchor, title, data) for anchor, title, data in [
        ('cold', '共享冷盘资产交接', cold), ('other', '补充项目证据与历史对照', other)] if data]
    for anchor, _, data in supplements:
        scope = 'cold-storage-scope.json' if anchor == 'cold' else 'other-current-scope.json'
        for key, name in [('scope_sha256', scope), ('excerpts_sha256', f'{anchor}-current-excerpts.json')]:
            if data[key] != sha256((root / name).read_bytes()).hexdigest():
                raise ValueError('补查盘点或摘录已变化，须重新核对引文。')
    if editorial:
        for key, name in [('lab_sha256', 'internal-review-edited.json'), ('directions_sha256', 'direction-review-edited.json')]:
            if editorial[key] != sha256((root / name).read_bytes()).hexdigest():
                raise ValueError('周会议题所用的校订稿已经改变，须按新来源重新核对。')
    if not all(row.get('editorial_review') for row in (lab, directions)):
        raise ValueError('周会读本需要校订后的内部复盘。')
    (root / 'internal-review.html').stat()
    authors = {m['id']: m['name'] for m in shared['members']}
    reports = {s['id']: s for s in shared['sources'] if s['kind'] in ('daily', 'weekly')}
    counts = Counter((authors[s['member_id']], s['kind']) for s in reports.values())
    if set(authors.values()) != set(lab['members_from_reviewed_reports']) or len(reports) != lab['signed_reports']:
        raise ValueError('团队报告版本和内部复盘的覆盖范围不一致。')

    def full_claim(section, text):
        fragment = quote(text[:58], safe='')
        return f'<a href="internal-review.html#{section}:~:text={fragment}">完整判断与出处</a>'

    meeting_record = ['# 实验室周会判断与取证记录', '',
                      '2026-11-21 · 内部研讨。取证范围、署名指纹与扫描限制记录于[核验条目](../../../experiments/2026-11-21-review-reading.md)。',
                      '以下议题来自已有材料的校订与本轮研判。复核建议由周会讨论决定；原报告中的计划可在[完整读本](meeting-brief.html)逐项对照。', '']

    def judgement_sources(section, fields, positions):
        refs = []
        evidence = []
        for key, index in positions:
            claim = fields[key][index]
            text = claim[1] if section == 'people' else claim['text']
            link = full_claim(section, text).replace('完整判断与出处', f'{dict(FIELDS)[key]} {index + 1}')
            refs.append(link)
            evidence.append(f'[{dict(FIELDS)[key]} {index + 1}](internal-review.html#{section}:~:text={quote(text[:58], safe="")})')
        meeting_record.append(' '.join(evidence))
        meeting_record.append('')
        return ' · '.join(refs)

    def signed_links(ref, name):
        if ref['member'] != name:
            raise ValueError('署名记录与成员不一致。')
        links = []
        for key in dict.fromkeys(r['id'] for r in ref['evidence']):
            source = reports[key]
            if authors[source['member_id']] != name:
                raise ValueError('成员判断引用了他人的报告。')
            url = source.get('url', '')
            if not url.startswith('https://rmp.wuwangwo.top/progress/#team?'):
                raise ValueError('报告原件缺少平台地址。')
            kind = '周报' if source['kind'] == 'weekly' else '日报'
            links.append(f'<a href="{escape(url, quote=True)}">{escape(source["date"])} {kind}</a>')
        return ' · '.join(links)

    def detail(section, fields, member=None, preview=None):
        chunks = []
        for key, label in FIELDS:
            items = [item for item in fields.get(key, []) if item is not preview]
            if not items and fields.get(key):
                continue
            chunks.append(f'<h4>{label}</h4><ul>')
            for item in items:
                if member:
                    ref, text = item
                    links = signed_links(lab['report_refs'][ref], member)
                else:
                    text = item['text']
                    links = full_claim(section, text)
                chunks.append(f'<li>{escape(text)} <small>{links}</small></li>')
            if not fields.get(key):
                chunks.append('<li>本期材料未给出可核对的记录。</li>')
            chunks.append('</ul>')
        return ''.join(chunks)

    day = datetime.fromisoformat(lab['generated_at']).date().isoformat()
    totals = Counter(s['kind'] for s in reports.values())
    coverage = (f'{len(authors)} 名成员的 {totals["weekly"]} 份周报、'
                f'{totals["daily"]} 份日报，'
                f'以及两台服务器 {lab["distinct_files"]} 份去重项目文档。')
    if cold:
        coverage += '另核对共享冷盘 4 份现行资产说明，同一文件的 24 份历史快照单列。'
    if other:
        coverage += '补充项目入口的 36 处观测合为 12 份独立正文，依原件日期区分本周进展和历史基础。'
    parts = [f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>实验室周会读本</title>
<style>*{{box-sizing:border-box}}body{{font:1rem/1.75 system-ui,"Microsoft YaHei",sans-serif;background:#f7f8fa;color:#101d2e;margin:0}}
main{{max-width:56rem;margin:auto;padding:clamp(1rem,4vw,3rem);overflow-wrap:anywhere}}header,section{{border-top:1px solid #bdc9d6;padding:1rem 0}}
h1,h2,h3,h4{{line-height:1.4}}h4{{margin:1rem 0 .3rem}}p,ul{{margin:.45rem 0}}ul{{padding-left:1.3rem}}
a{{color:#174b83;text-underline-offset:.2rem}}summary{{cursor:pointer;padding:.65rem 0;font-weight:650}}small,p.meta{{color:#536276}}
article{{background:white;border:1px solid #d8dfe8;border-radius:.5rem;padding:clamp(.8rem,2vw,1.35rem);margin:.8rem 0}}
article h3{{margin:0 0 .4rem}}nav{{display:flex;flex-wrap:wrap;gap:1rem}}:focus-visible{{outline:3px solid #174b83;outline-offset:2px}}</style></head>
<body><main><header><p class="meta">内部研讨 · 复盘日期 {day}</p><h1>实验室周会读本</h1>
<p>{escape(coverage)}个人贡献以本人署名报告为据；方向复盘另结合项目原件。何锋的 TFBS 研究已按路径与正文排除。</p>
<nav aria-label="读本目录"><a href="#lab">实验室判断</a><a href="#topics">方向与问题</a><a href="#people">成员与报告</a><a href="internal-review.html#scope">核对覆盖</a></nav></header>
<section id="lab"><h2>实验室判断</h2>''']
    if editorial:
        parts.append('<h3>下次周会优先讨论</h3>')
        meeting_record.extend(['## 周会优先讨论', ''])
        for title, text, direction, *refs in editorial['decisions']:
            fields = lab['lab'] if direction == -1 else directions['directions'][direction]['claims']
            meeting_record.extend([f'### {title}', '', text, ''])
            links = judgement_sources('lab' if direction == -1 else 'directions', fields, refs)
            parts.append(f'<article><h3>{escape(title)}</h3><p>{escape(text)}</p><small>判断依据 · {links}</small></article>')
        parts.append('<details><summary>本期实验室实测结果</summary>')
    for claim in lab['lab']['result']:
        text = claim['text']
        parts.append(f'<article><p>{escape(text)}</p><small>{full_claim("lab", text)}</small></article>')
    if editorial:
        parts.append('</details>')
    parts.append('<details><summary>本期共同阻塞与优先验证</summary>')
    for key in ('limit', 'next'):
        for claim in lab['lab'][key]:
            text = claim['text']
            parts.append(f'<p>{escape(text)} <small>{full_claim("lab", text)}</small></p>')
    parts.append('</details>')
    for anchor, title, data in supplements:
        proofs = data['evidence']
        meeting_record.extend([f'## {title}', '', data['summary'], ''])
        parts.append(f'<article id="{anchor}"><h3>{title}</h3><p>{escape(data["summary"])}</p><details><summary>分项判断、范围与依据</summary>')
        for item in data['findings']:
            keys = item['refs']
            if not keys or any(key not in proofs for key in keys):
                raise ValueError('补查判断缺少已核对的摘录。')
            period = item.get('period', '')
            citations = ' · '.join(f'<a href="#{anchor}-{escape(key)}">{escape(key)}</a>' for key in keys)
            parts.append(f'<h4 id="{anchor}-finding-{escape(keys[0])}">{escape(item["title"])}</h4><small>{escape(period)}</small><p>{escape(item["text"])}</p><small>{citations}</small>')
            links = ' · '.join(f'[{key}](meeting-brief.html#{anchor}-{key})' for key in keys)
            meeting_record.extend([f'### {item["title"]}', '', period, item['text'], '', links, ''])
        parts.append(f'<details><summary>核对 {len(proofs)} 段原件摘录</summary>')
        for key, proof in proofs.items():
            parts.append(f'<p id="{anchor}-{escape(key)}" tabindex="-1"><strong>{escape(key)}</strong> · {escape(proof["source"])}<br>{escape(proof["quote"])}</p>')
        review = data.get('model_review')
        if review:
            meeting_record.extend([f'模型复核采用 {review["model"]} / {review["reasoning_effort"]}，'
                                   f'{review["request_count"]} 次调用，{review["total_tokens"]:,} 个服务商计量 token。'
                                   f'逐项复核 {len(review["checks"])} 项，原件摘录 {len(proofs)} 段。', ''])
            for check in review['checks']:
                meeting_record.append(f'- {check["source"]} · {check["decision"]}')
        meeting_record.append('')
        parts.append('</details></details></article>')
    parts.append('</section><section id="topics"><h2>按研究问题讨论</h2>')
    meeting_record.extend(['## 按方向的判断', ''])
    for index, row in enumerate(directions['directions']):
        fields = row['claims']
        result = next(iter(fields['result']), None)
        text = result['text'] if result else '本期材料未提供可核对的结果。'
        if editorial:
            label, text, *refs = editorial['directions'][index]
            meeting_record.extend([f'### {label}', '', text, ''])
            source = judgement_sources('directions', fields, refs)
            title = label
            result = None
        else:
            source = full_claim('directions', text) if result else ''
            title = row['question']
        resource = ''
        if cold and title in cold['relevant_topics']:
            resource = f'<p class="meta">{escape(cold["relevant_topics"][title])} <a href="#cold">核对资产交接记录</a></p>'
            meeting_record.extend([cold['relevant_topics'][title], '[资产交接](meeting-brief.html#cold)', ''])
        project_key = {'检索、可答性与长时记忆':'long_context_memory', '跨来源认知障碍分类':'language_health', '语音处理与协作标注':'speech_pipeline'}.get(title)
        if other and project_key in other['relevant_topics']:
            note = other['relevant_topics'][project_key]
            resource += f'<p class="meta">{escape(note)} <a href="#other">核对项目证据</a></p>'
            meeting_record.extend([note, '[补充项目证据](meeting-brief.html#other)', ''])
        parts.append(f'<article><h3>{escape(title)}</h3><p>{escape(text)}</p><small>{source}</small>{resource}<details><summary>{escape(row["question"])}</summary>{detail("directions", fields, preview=result)}</details></article>')
    if other and other.get('supplementary_topic'):
        topic = other['supplementary_topic']
        if any(key not in other['evidence'] for key in topic['refs']):
            raise ValueError('补充方向缺少可核对的证据。')
        links = ' · '.join(f'<a href="#other-{escape(key)}">{escape(key)}</a>' for key in topic['refs'])
        parts.append(f'<article><h3>{escape(topic["title"])}</h3><p>{escape(topic["summary"])}</p><small>{links}</small></article>')
        mdlinks = ' · '.join(f'[{key}](meeting-brief.html#other-{key})' for key in topic['refs'])
        meeting_record.extend([f'### {topic["title"]}', '', topic['summary'], '', mdlinks, ''])
    parts.append('</section><section id="people"><h2>按署名成员同步</h2>')
    meeting_record.extend(['## 署名成员与个人贡献', ''])
    for _, _, data in supplements:
        parts.append(f'<p class="meta">{escape(data["attribution"])}</p>')
        meeting_record.extend([data['attribution'], ''])
    for name, fields in lab['members_from_reviewed_reports'].items():
        stages = fields.get('progress') or fields.get('result') or []
        preview = stages[0] if stages else None
        overview = preview[1] if preview else '本期没有可核对的署名进展。'
        if editorial:
            overview, *refs = editorial['members'][name]
            meeting_record.extend([f'### {name} · 周报 {counts[name,"weekly"]}、日报 {counts[name,"daily"]}', '', overview, ''])
            source = judgement_sources('people', fields, refs)
            preview = None
        else:
            source = signed_links(lab['report_refs'][preview[0]], name) if preview else ''
        parts.append(f'<article><h3>{escape(name)}</h3><small>周报 {counts[name,"weekly"]} · 日报 {counts[name,"daily"]}</small><p>{escape(overview)}</p><small>{source}</small><details><summary>个人进展、结果、阻塞与计划</summary>{detail("people", fields, name, preview)}</details></article>')
    parts.append('</section><p><a href="internal-review.html#studies">逐项目查看原件与取证范围</a></p></main></body></html>')
    return ''.join(parts), '\n'.join(meeting_record) if editorial else None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('private_review_directory', type=Path)
    directory = parser.parse_args().private_review_directory.resolve(strict=True)
    reader, record = build(directory)
    for name, content in [('meeting-brief.html', reader), ('meeting-evidence.md', record)]:
        if content is not None:
            with NamedTemporaryFile(mode='w', dir=directory, encoding='utf-8', delete=False) as f:
                f.write(content)
            os.replace(f.name, directory / name)
