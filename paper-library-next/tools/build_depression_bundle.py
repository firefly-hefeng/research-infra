"""Build a portable, deduplicated bibliography bundle; never alter source files."""
import argparse
import csv
import hashlib
import json
import re
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# These three exceptions were checked on the PDF's first rendered page, 2026-10-28.
# Bind corrections to bytes, never a filename alone; do not infer years from filenames.
VERIFIED_FRONT_PAGES = {
    '96f134d1b86b17b37a0010efc4a4810df61499594a9bc0b1af57b108f4413797': {
        'title': '医疗器械产品注册技术审评报告：抑郁症状辅助治疗软件（CQZ2402211）',
        'authors': ['国家药品监督管理局医疗器械技术审评中心'], 'year': None,
        'venue': '', 'doi': '', 'category': '医疗器械与监管',
        'summary': '抑郁症状辅助治疗软件的医疗器械产品注册技术审评报告；受理号 CQZ2402211。首页未列出版年份，年份保持未知。',
        'source_record_ids': ['V2C18']},
    'd8e900e6ba9256f3020362aa1845ddb74909f6cac61a33c8552076b40f5f0c82': {
        'title': 'Bridging the Divide: Clinical Reflections on Guilt, Shame, and Emotional Integration in First-Generation Immigrants Through GIM Therapy',
        'authors': ['Carla Chikhani'], 'year': 2025,
        'venue': 'Journal of the Association for Music and Imagery, Vol. 22, 97–119',
        'doi': '10.59451/jami.88026', 'category': '音乐疗法',
        'summary': '关于引导意象与音乐（GIM）及文化身份、羞耻和情绪表达的多案例研究。属于关联干预文献，不等同抑郁语音识别算法证据。',
        'source_record_ids': ['M01']},
    'f625757d62d0ff39ee2a6df41e40d806db911d826dece35b65ace99bb9ceef83': {
        'title': 'JADAI: Jointly Amortizing Adaptive Design and Bayesian Inference',
        'authors': ['Niels Bracher', 'Lars Kühmichel', 'Desi R. Ivanova', 'Xavier Intes', 'Paul-Christian Bürkner', 'Stefan T. Radev'],
        'year': 2026, 'venue': 'Proceedings of the 43rd International Conference on Machine Learning, PMLR 306',
        'doi': '', 'category': '通用方法支撑',
        'summary': '联合自适应实验设计与贝叶斯推断的通用方法，作为方法学背景保存；不是抑郁语音识别实证工作。',
        'source_record_ids': ['M02']},
}


def apply_front_page_check(metadata, sha):
    if sha in VERIFIED_FRONT_PAGES:
        metadata.update(VERIFIED_FRONT_PAGES[sha])
        metadata['tags'] = [metadata['category']]
        metadata['provenance'] = [{'label': 'PDF 第 1 页题录与摘要核对（2026-10-28）；未作全文精读',
                                   'sha256': sha, 'record_id': metadata['source_record_ids'][0]}]


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def build(source, output):
    source, output = Path(source).resolve(), Path(output).absolute()
    if output.exists() or output.is_relative_to(source):
        raise ValueError('Output must be a new directory outside the source collection')
    index = source / '抑郁症语音特征与识别/00_索引与检索/分类文献数据库.json'
    master = source / '00_文献清单/文献总表.csv'
    classified = json.loads(index.read_text(encoding='utf-8-sig'))['records']
    with master.open(encoding='utf-8-sig', newline='') as stream:
        original = list(csv.DictReader(stream))
    sources = [{'label': '已整理分类文献数据库', 'sha256': digest(index)},
               {'label': '方向一/二文献总表', 'sha256': digest(master)}]
    by_path, by_id = {}, {}
    for entry in classified:
        item = dict(entry, provenance=dict(sources[0], record_id=entry['id']))
        by_id[entry['id']] = item
        for alias in entry.get('legacy_ids', []):
            by_id.setdefault(alias, item)
        if entry.get('local_pdf'):
            by_path['抑郁症语音特征与识别/' + entry['local_pdf'].replace('\\', '/')] = item
    for entry in original:
        ident = entry['ID']
        summary = entry.get('核心贡献', '')
        if summary.startswith('http'):
            summary = ''  # Some historical CSV rows have a shifted URL column.
        by_id.setdefault(ident, dict(id=ident, title=entry.get('标题', ''),
            authors=entry.get('作者', ''), year=entry.get('年份'), venue=entry.get('来源', ''),
            doi=entry.get('DOI', ''), category=entry.get('类别', ''), summary=summary,
            provenance=dict(sources[1], record_id=ident)))
    output.mkdir(parents=True, mode=0o700)
    (output / 'objects').mkdir(mode=0o700)
    unique, audit, metadata_checks = {}, [], []
    try:
        import fitz
    except ImportError:
        fitz = None
    # Only curated literature roots; do not enumerate environments, downloads, or experiments.
    for relative_root in ['抑郁症语音特征与识别', '04_文献PDF']:
        for path in sorted((source / relative_root).rglob('*.pdf')):
            relative = path.relative_to(source)
            if '原始核验记录' in relative.parts:
                continue
            if any(parent.is_symlink() for parent in [path, *path.parents] if parent != source.parent):
                raise ValueError('Symlink source is not allowed')
            before = path.stat()
            sha = digest(path)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError('Source changed during inventory')
            ident = re.match(r'^([A-Z]+\d+)', path.name)
            entry = by_path.get(relative.as_posix()) or by_id.get(ident.group(1) if ident else '')
            pdf_meta, pages = {}, None
            if fitz:
                try:
                    with fitz.open(path) as pdf:
                        pdf_meta, pages = pdf.metadata or {}, pdf.page_count
                except Exception as exc:
                    raise ValueError('Unreadable PDF: ' + path.name) from exc
            audit.append({'relative_path': relative.as_posix(), 'local_path': str(path),
                          'sha256': sha, 'size_bytes': after.st_size,
                          'record_id': entry.get('id') if entry else None, 'pages': pages,
                          'pdf_metadata_title': pdf_meta.get('title') or None})
            if sha in unique:
                unique[sha]['source_file_count'] += 1
                continue
            title = (entry or {}).get('title') or pdf_meta.get('title') or path.stem
            if any(word in path.stem.lower() for word in ['supplement', '_supp', '_appendix']):
                title = '补充材料：' + title
            author = (entry or {}).get('authors') or ''
            authors = [part.strip() for part in author.split(';') if part.strip()] if ';' in author else ([author.strip()] if author.strip() else [])
            year = str((entry or {}).get('year') or '')
            year = int(year) if year.isdigit() and 1800 <= int(year) <= 2028 else None
            category = re.sub(r'^\d+_', '', (entry or {}).get('category') or '未分类文献')
            metadata = {'title': title[:600], 'authors': authors[:100], 'year': year,
                'venue': ((entry or {}).get('venue') or '')[:200], 'doi': ((entry or {}).get('doi') or '')[:200],
                'summary': ((entry or {}).get('summary') or '已收录本地原件；具体用途说明待补充。')[:5000],
                'category': category[:100], 'tags': [category[:60]],
                'source_record_ids': [(entry or {}).get('id')] if entry else [],
                'provenance': [(entry or {})['provenance']] if entry else [{'label': 'PDF 自带元数据或文件名；作者年份待核对', 'sha256': sha}],
                'review_state': 'bibliography_only', 'fulltext_policy': 'restricted'}
            apply_front_page_check(metadata, sha)
            dest = output / 'objects' / (sha + '.pdf')
            shutil.copyfile(path, dest)
            if digest(dest) != sha:
                raise ValueError('Copy verification failed')
            dest.chmod(0o600)
            unique[sha] = {'id': sha, 'pdf': 'objects/' + sha + '.pdf', 'filename': path.name,
                           'size_bytes': after.st_size, 'pages': pages,
                           'source_file_count': 1, 'metadata': metadata}
            if len(metadata_checks) < 8 and pdf_meta.get('title'):
                metadata_checks.append({'record_id': (entry or {}).get('id'),
                    'catalog_title': title, 'pdf_metadata_title': pdf_meta['title'], 'pages': pages})
    manifest = {'schema_version': '1.0', 'collection_id': 'depression-speech-20261028',
        'title': '抑郁症语音识别、疗法与实现文献',
        'created_at': datetime.now(timezone.utc).isoformat(), 'bibliographic_sources': sources,
        'source_file_count': len(audit), 'unique_pdf_count': len(unique),
        'counting_note': '按 PDF 字节 SHA-256 去重；不同版本或补充材料仍独立，不等同独立论文数。题录继承已有索引，本轮未逐篇重新精读或核验学术结论。',
        'items': list(unique.values())}
    manifest_path = output / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    manifest_path.chmod(0o600)
    audit_path = output.parent / (output.name + '-audit.private.json')
    audit_path.write_text(json.dumps({'source_root': str(source), 'files': audit,
        'pdf_metadata_samples': metadata_checks}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    audit_path.chmod(0o600)
    report = {'bundle': str(output), 'manifest_sha256': digest(manifest_path),
              'source_files': len(audit), 'unique_pdfs': len(unique),
              'bytes': sum(item['size_bytes'] for item in unique.values()),
              'duplicate_copies': len(audit) - len(unique),
              'matched_metadata': sum(bool(item['metadata']['source_record_ids']) for item in unique.values()),
              'topics': dict(Counter(item['metadata']['category'] for item in unique.values()))}
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output), ensure_ascii=False, indent=2))
