"""Source-grounded reading notes stored separately from cards and imported records."""
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid
import unicodedata
from xml.etree import ElementTree

from .library import ID, digest, normalize, now

SUMMARY_FIELDS = ('overview', 'problem', 'method', 'findings', 'limitations')
MAX_INPUT_BYTES = 160000


def ocr_text(source):
    """Optional English scan OCR; run only from explicit source/insight CLI work."""
    binaries = {name: shutil.which(name) for name in ('pdfinfo', 'pdftoppm', 'tesseract')}
    if not all(binaries.values()):
        raise ValueError('未提取到正文；英文扫描件需要安装 Poppler 和 Tesseract 后进行 OCR')
    env = {**os.environ, 'LC_ALL': 'C', 'OMP_THREAD_LIMIT': '1'}
    info = subprocess.run([binaries['pdfinfo'], str(source)], check=True, capture_output=True,
                          text=True, timeout=30, env=env).stdout
    match = re.search(r'^Pages:\s+(\d+)', info, re.M)
    if not match or not 1 <= int(match[1]) <= 30:
        raise ValueError('自动 OCR 仅支持 1–30 页扫描件，请分段处理')
    result = []
    with tempfile.TemporaryDirectory(prefix='paper-insight-ocr-') as folder:
        for page in range(1, int(match[1]) + 1):
            target = Path(folder) / 'page'
            subprocess.run([binaries['pdftoppm'], '-f', str(page), '-l', str(page),
                            '-r', '300', '-singlefile', '-gray', '-png', str(source), str(target)],
                           check=True, capture_output=True, timeout=60, env=env)
            text = subprocess.run([binaries['tesseract'], str(target) + '.png', 'stdout', '-l', 'eng', '--psm', '3'],
                                  check=True, capture_output=True, text=True, timeout=90, env=env).stdout
            result.append(text.replace('\f', '').rstrip() + '\n')
    return '\f'.join(result) + '\f'


def source_method(library, paper_id):
    meta = library.safe('.paperlib/insights/source/' + paper_id + '.meta.json')
    if meta.exists():
        data = json.loads(meta.read_text())
        if data.get('source_digest') == paper_id and data.get('method') == 'ocr':
            return 'ocr'
    return 'pdf_text'


def source_text(library, paper_id):
    """Use reading-order extraction, separate from legacy layout-based card evidence."""
    source = library.pdf_path(paper_id)
    if digest(source) != paper_id:
        raise ValueError('PDF 内容已变化，不能生成导读依据')
    for relative in ('.paperlib/insights', '.paperlib/insights/source'):
        library.safe(relative).mkdir(mode=0o700, exist_ok=True)
    cache = library.safe('.paperlib/insights/source/' + paper_id + '.txt')
    if cache.exists():
        if cache.stat().st_size > 8 * 1024 * 1024:
            raise ValueError('导读正文缓存超出 8 MiB')
        return cache.read_text(encoding='utf-8')
    executable = shutil.which('pdftotext')
    if not executable:
        raise RuntimeError('缺少 pdftotext，请安装 Poppler')
    handle, temporary = tempfile.mkstemp(prefix='.source-', dir=cache.parent)
    try:
        with os.fdopen(handle, 'wb') as output:
            os.chmod(temporary, 0o600)
            try:
                subprocess.run([executable, str(source), '-'], stdout=output,
                               stderr=subprocess.PIPE, timeout=90, check=True)
            except (subprocess.SubprocessError, OSError) as exc:
                raise RuntimeError('PDF 阅读顺序文本提取失败: ' + type(exc).__name__) from None
            output.flush()
            os.fsync(output.fileno())
        temporary_path = Path(temporary)
        if temporary_path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError('导读正文超出 8 MiB，需人工分段处理')
        text = temporary_path.read_text(encoding='utf-8')
        method = 'pdf_text'
        if len(normalize(text)) < 20:
            try:
                text = ocr_text(source)
            except (subprocess.SubprocessError, OSError) as exc:
                raise RuntimeError('扫描件 OCR 失败: ' + type(exc).__name__) from None
            method = 'ocr'
            if len(normalize(text)) < 20 or len(text.encode('utf-8')) > 8 * 1024 * 1024:
                raise ValueError('OCR 未能取得可用正文，请人工核对扫描件')
            temporary_path.write_text(text, encoding='utf-8')
        if digest(source) != paper_id:
            raise ValueError('提取期间 PDF 内容发生变化')
        write_import_log(cache.with_suffix('.meta.json'), {'source_digest': paper_id, 'method': method})
        os.replace(temporary, cache)
        return text
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def object_fields(value, allowed, label):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError(label + ' 必须是仅含已定义字段的对象')


def text_value(value, label, maximum, required=False):
    if not isinstance(value, str) or len(value) > maximum or '\x00' in value:
        raise ValueError(label + ' 不是有效文本')
    value = value.strip()
    if required and not value:
        raise ValueError(label + ' 不能为空')
    return value


def keyword_text(text):
    # Ignore typesetting whitespace and discretionary hyphens, retaining case and accents.
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text).replace('\u00ad', ''))


def keyword_layout_blocks(pdf, page):
    # Poppler preserves printed hyphens and separates columns in its bounding-box output.
    try:
        result = subprocess.run(['pdftotext', '-f', str(page), '-l', str(page),
                                 '-bbox-layout', str(pdf), '-'], check=True, capture_output=True,
                                timeout=30)
        root = ElementTree.fromstring(result.stdout)
    except (OSError, subprocess.SubprocessError, ElementTree.ParseError) as exc:
        raise ValueError('无法校验作者关键词的原页拼写') from exc
    return [keyword_text(''.join(block.itertext())) for block in root.findall('.//{*}block')]


def validate_author_keywords(value, pages, pdf=None):
    if value is None:
        return None
    object_fields(value, ('terms', 'evidence'), 'author_keywords')
    terms, evidence = value.get('terms'), value.get('evidence')
    if not isinstance(terms, list) or not 1 <= len(terms) <= 100:
        raise ValueError('作者关键词必须是原文列出的非空词表')
    terms = [text_value(term, 'author_keywords.terms', 320, required=True) for term in terms]
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 60:
        raise ValueError('作者关键词须提供关键词栏的原文依据')
    refs, displayed_quotes, layouts = [], [], {}
    for entry in evidence:
        object_fields(entry, ('page', 'quote', 'glyph_corrections', 'layout_hyphens'), 'author_keywords.evidence')
        page = entry.get('page')
        quote = text_value(entry.get('quote'), 'author_keywords.evidence.quote', 6000, required=True)
        if type(page) is not int or not 1 <= page <= len(pages):
            raise ValueError('作者关键词依据页码无效')
        if keyword_text(quote) not in keyword_text(pages[page - 1]):
            raise ValueError('作者关键词引文无法在指定页匹配')
        ref = {'page': page, 'quote': quote}
        displayed = quote
        corrections = entry.get('glyph_corrections', [])
        if not isinstance(corrections, list) or len(corrections) > 8:
            raise ValueError('无效的 PDF 字形校对记录')
        for correction in corrections:
            object_fields(correction, ('raw', 'text'), 'glyph_corrections')
            raw, replacement = correction.get('raw'), correction.get('text')
            if not (isinstance(raw, str) and len(raw) == 1 and raw in displayed and
                    unicodedata.category(raw) == 'Cc' and not raw.isspace() and
                    isinstance(replacement, str) and len(replacement) == 1 and
                    unicodedata.category(replacement)[0] in ('L', 'N', 'S')):
                raise ValueError('字形校对仅允许替换提取错误的单个控制字符')
            displayed = displayed.replace(raw, replacement)
        if corrections:
            ref['glyph_corrections'] = corrections
        hyphens = entry.get('layout_hyphens', [])
        if not isinstance(hyphens, list) or len(hyphens) > 32:
            raise ValueError('无效的关键词连字符校对记录')
        for correction in hyphens:
            object_fields(correction, ('joined', 'printed'), 'layout_hyphens')
            joined = text_value(correction.get('joined'), 'joined', 320, True)
            printed = text_value(correction.get('printed'), 'printed', 320, True)
            if (joined not in displayed or not any(
                    printed[:i] + printed[i + 1:] == joined
                    for i, char in enumerate(printed) if char in '-‐‑')):
                raise ValueError('关键词拼写校对仅允许恢复单个印刷连字符')
            if page not in layouts:
                layouts[page] = keyword_layout_blocks(pdf, page)
            if not any(keyword_text(printed) in block for block in layouts[page]):
                raise ValueError('关键词连字符无法在原页排版中核实: ' + printed)
            displayed = displayed.replace(joined, printed)
        if hyphens:
            ref['layout_hyphens'] = hyphens
        refs.append(ref)
        displayed_quotes.append(displayed)
    block = keyword_text(' '.join(displayed_quotes))
    heading = re.search(r'keywords?(?:andphrases)?|keyphrases|indexterms|indexingterms|'
                        r'关键词|关键字|關鍵詞|關鍵字', block, re.I)
    if not heading:
        raise ValueError('原文依据中未找到作者关键词栏目标题')
    after = heading.end()
    for term in terms:
        literal = keyword_text(term)
        pos = block.find(literal, after)
        if pos < 0:
            raise ValueError('作者关键词无法按原文顺序匹配: ' + term)
        after = pos + len(literal)
    return {'terms': terms, 'evidence': refs}


def validate_insight(library, paper_id, value):
    """Verify literal source spans; this does not establish semantic correctness/completeness."""
    object_fields(value, ('schema_version', 'paper_id', 'source_digest', 'abstract',
                         'keywords', 'keywords_source', 'author_keywords', 'summary', 'evidence',
                         'coverage', 'generated_by', 'updated_at', 'source_method'), 'insight')
    if type(value.get('schema_version')) is not int or value['schema_version'] != 1:
        raise ValueError('insight.schema_version 必须为 1')
    for key in ('paper_id', 'source_digest'):
        if key in value and value[key] != paper_id:
            raise ValueError(key + ' 与目标论文 ID 不一致')
    source = library.pdf_path(paper_id)
    if digest(source) != paper_id:
        raise ValueError('PDF 内容已变化，不能保存导读')
    abstract = value.get('abstract')
    object_fields(abstract, ('status', 'text', 'language', 'pages', 'reason', 'segments', 'segment_order'), 'abstract')
    status = abstract.get('status')
    if status not in ('available', 'missing'):
        raise ValueError('abstract.status 必须为 available 或 missing')
    summary = value.get('summary')
    object_fields(summary, SUMMARY_FIELDS, 'summary')
    clean_summary = {field: text_value(summary.get(field, ''), 'summary.' + field, 6000,
                                      required=field == 'overview' and status == 'available')
                     for field in SUMMARY_FIELDS}
    for field, text in clean_summary.items():
        if text and not any('\u3400' <= char <= '\u9fff' for char in text):
            raise ValueError('summary.' + field + ' 请使用中文概括')
    evidence = value.get('evidence', [])
    if not isinstance(evidence, list) or len(evidence) > 50:
        raise ValueError('evidence 必须是最多 50 项的列表')
    # A missing abstract with no claimed interpretation needs no fabricated source text.
    content = source_text(library, paper_id) if status == 'available' or any(clean_summary.values()) or evidence or value.get('author_keywords') else ''
    pages = content.split('\f')
    if pages and not pages[-1].strip():
        pages.pop()
    if status == 'available':
        if abstract.get('reason'):
            raise ValueError('available 摘要不能同时包含 missing reason')
        text = text_value(abstract.get('text'), 'abstract.text', 24000, required=True)
        if len(normalize(text)) < 20:
            raise ValueError('abstract.text 过短，需提供完整原文摘要')
        language = abstract.get('language')
        if language not in ('en', 'zh', 'other'):
            raise ValueError('abstract.language 必须为 en、zh 或 other')
        selected = abstract.get('pages')
        if not isinstance(selected, list) or not 1 <= len(selected) <= 6 or any(
                type(page) is not int or not 1 <= page <= len(pages) for page in selected):
            raise ValueError('abstract.pages 须包含 1–6 个有效 PDF 页码')
        if selected != list(range(selected[0], selected[-1] + 1)):
            raise ValueError('abstract.pages 须为从小到大连续且不重复的页码')
        clean_abstract = {'status': 'available', 'text': text, 'language': language, 'pages': selected}
        segments = abstract.get('segments')
        order = abstract.get('segment_order', 'extraction_order')
        if order not in ('extraction_order', 'reading_order') or (segments is None and 'segment_order' in abstract):
            raise ValueError('segment_order 仅用于 segments，须为 extraction_order 或 reading_order')
        if segments is not None:
            if not isinstance(segments, list) or not 1 <= len(segments) <= 30:
                raise ValueError('abstract.segments 须为 1–30 个按原文顺序排列的摘要片段')
            clean_segments, last_page, last_end, used_spans = [], 0, 0, {}
            for segment in segments:
                object_fields(segment, ('page', 'text'), 'abstract.segments')
                page = segment.get('page')
                segment_text = text_value(segment.get('text'), 'abstract.segments.text', 24000, True)
                if type(page) is not int or page not in selected or page < last_page:
                    raise ValueError('摘要片段页码不符或顺序颠倒')
                normalized = normalize(pages[page - 1])
                offset = normalized.find(normalize(segment_text), last_end if page == last_page and order == 'extraction_order' else 0)
                size = len(normalize(segment_text))
                occupied = used_spans.setdefault(page, [])
                while offset >= 0 and any(offset < end and offset + size > start for start, end in occupied):
                    offset = normalized.find(normalize(segment_text), offset + 1)
                if offset < 0:
                    raise ValueError('摘要片段无法按原文顺序匹配')
                last_page, last_end = page, offset + size
                occupied.append((offset, last_end))
                clean_segments.append({'page': page, 'text': segment_text})
            if sorted({x['page'] for x in clean_segments}) != selected or normalize(text) != normalize(''.join(x['text'] for x in clean_segments)):
                raise ValueError('完整摘要必须与已核对的片段拼接内容一致')
            clean_abstract['segments'] = clean_segments
            if order == 'reading_order':
                clean_abstract['segment_order'] = order
        elif normalize(text) not in normalize('\n'.join(pages[page - 1] for page in selected)):
            raise ValueError('完整摘要无法在指定 PDF 页连续匹配，请保留原文或提交逐页 segments 去除页眉页脚')
    else:
        if abstract.get('text') or abstract.get('pages') or abstract.get('language') or abstract.get('segments') or abstract.get('segment_order'):
            raise ValueError('missing 摘要只填写 reason，不使用其他内容代替摘要')
        clean_abstract = {'status': 'missing', 'reason': text_value(
            abstract.get('reason'), 'abstract.reason', 1000, required=True)}
    keywords = value.get('keywords', [])
    if not isinstance(keywords, list) or not (
            3 <= len(keywords) <= 8 or (status == 'missing' and not keywords)):
        raise ValueError('keywords 须有 3–8 个主题词；摘要缺失时可留空')
    clean_keywords = [text_value(word, 'keywords', 80, required=True) for word in keywords]
    if len({normalize(word) for word in clean_keywords}) != len(clean_keywords):
        raise ValueError('keywords 不可重复')
    if value.get('keywords_source', 'curated') != 'curated':
        raise ValueError('keywords_source 必须为 curated，主题词不冒充作者关键词')
    coverage = value.get('coverage')
    if coverage not in ('abstract', 'selected_pages', 'full_text'):
        raise ValueError('coverage 必须为 abstract、selected_pages 或 full_text')
    if status == 'missing' and coverage == 'abstract' and any(clean_summary.values()):
        raise ValueError('摘要缺失时不能声称基于摘要生成了总结')
    generated_by = value.get('generated_by')
    if generated_by not in ('codex', 'agent', 'api', 'manual'):
        raise ValueError('generated_by 必须为 codex、agent、api 或 manual')
    clean_evidence = []
    for index, entry in enumerate(evidence):
        object_fields(entry, ('field', 'page', 'quote'), f'evidence[{index}]')
        field, page = entry.get('field'), entry.get('page')
        if field not in tuple('summary.' + name for name in SUMMARY_FIELDS):
            raise ValueError('导读证据的 field 须对应 summary 字段')
        if not clean_summary[field.split('.')[1]]:
            raise ValueError('空总结字段不应包含证据')
        quote = text_value(entry.get('quote'), 'evidence.quote', 6000, required=True)
        if type(page) is not int or not 1 <= page <= len(pages) or len(normalize(quote)) < 8:
            raise ValueError('导读证据页码或引文长度无效')
        if normalize(quote) not in normalize(pages[page - 1]):
            raise ValueError(f'{field} 引文无法在 PDF 第 {page} 页匹配')
        if coverage == 'abstract' and normalize(quote) not in normalize(clean_abstract.get('text', '')):
            raise ValueError('coverage=abstract 时证据必须来自原文摘要')
        clean_evidence.append({'field': field, 'page': page, 'quote': quote})
    required = {'summary.' + field for field, text in clean_summary.items() if text}
    if required - {item['field'] for item in clean_evidence}:
        raise ValueError('导读缺少字段证据: ' + ', '.join(sorted(required - {item['field'] for item in clean_evidence})))
    result = {'schema_version': 1, 'source_digest': paper_id, 'abstract': clean_abstract,
            'keywords': clean_keywords, 'keywords_source': 'curated', 'summary': clean_summary,
            'evidence': clean_evidence, 'coverage': coverage, 'generated_by': generated_by,
            'source_method': source_method(library, paper_id)}
    if 'author_keywords' in value:
        result['author_keywords'] = validate_author_keywords(value['author_keywords'], pages, source)
    return result


def public_insight(value):
    """Only the documented reading data can enter the anonymous catalog."""
    if not isinstance(value, dict):
        return None
    result = {key: value[key] for key in ('schema_version', 'source_digest', 'keywords',
              'keywords_source', 'coverage', 'generated_by', 'updated_at', 'source_method') if key in value}
    for key, allowed in (('abstract', ('status', 'text', 'language', 'pages', 'reason')),
                         ('summary', SUMMARY_FIELDS)):
        part = value.get(key) or {}
        result[key] = {name: part[name] for name in allowed if name in part}
    authors = value.get('author_keywords')
    if authors and authors.get('terms'):
        refs = []
        for entry in authors.get('evidence', []):
            quote = entry['quote']
            for correction in entry.get('glyph_corrections', []):
                quote = quote.replace(correction['raw'], correction['text'])
            for correction in entry.get('layout_hyphens', []):
                quote = quote.replace(correction['joined'], correction['printed'])
            refs.append({'page': entry['page'], 'quote': quote})
        result['author_keywords'] = {'terms': authors['terms'], 'evidence': refs}
    result['evidence'] = [{key: item[key] for key in ('field', 'page', 'quote') if key in item}
                          for item in value.get('evidence', []) if isinstance(item, dict)]
    return result


def read_insight(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError('导读输入须为不超过 160 KB 的普通 JSON 文件')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('导读 JSON 出现重复字段: ' + key)
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique)


def write_import_log(path, result):
    handle, temporary = tempfile.mkstemp(prefix='.import-', dir=path.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            os.chmod(temporary, 0o600)
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def import_insights(library, folder, check=False):
    folder = Path(folder)
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError('导读批次必须是普通目录')
    files = sorted(folder.glob('*.json'))
    if not files:
        raise ValueError('目录中没有 <论文ID>.json 导读文件')
    log_dir = library.safe('.paperlib/insights')
    log_dir.mkdir(mode=0o700, exist_ok=True)
    log_name = 'import-' + uuid.uuid4().hex + '.json'
    log = library.safe('.paperlib/insights/' + log_name)
    result = {'schema_version': 1, 'mode': 'check' if check else 'commit', 'started_at': now(),
              'total': len(files), 'valid': 0, 'saved': 0, 'unchanged': 0, 'failed': 0,
              'items': [], 'log_file': '.paperlib/insights/' + log_name}
    write_import_log(log, result)
    for path in files:
        paper_id = path.stem
        entry = {'file': path.name}
        try:
            if not ID.fullmatch(paper_id):
                raise ValueError('文件名必须是 <完整64位论文ID>.json')
            value = read_insight(path)
            if check:
                validate_insight(library, paper_id, value)
                entry['status'] = 'valid'
            else:
                saved = library.commit_insight(paper_id, value)
                entry['status'] = 'saved' if saved['changed'] else 'unchanged'
                result[entry['status']] += 1
            result['valid'] += 1
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            entry.update(status='failed', error=str(exc)[:500])
            result['failed'] += 1
        result['items'].append(entry)
        write_import_log(log, result)
    result['finished_at'] = now()
    write_import_log(log, result)
    return result
