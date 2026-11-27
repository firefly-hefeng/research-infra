"""Daily reports and private originals, stored separately from weekly summary inputs."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile
from pypdf.errors import PdfReadError
from . import intake
from .core import atomic_write, atomic_write_bytes, child, read_text, write_json
from .reports import PLACEHOLDER, validate_fields

FIELDS = {'done': '今日完成', 'results': '结果与证据', 'blockers': '问题与阻塞', 'next': '明日计划'}
MAX_ATTACHMENTS = 8
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
BODY_EXTENSIONS = {'.md', '.markdown', '.txt', '.csv', '.docx', '.xlsx', '.pptx', '.pdf'}


class DailyConflict(ValueError):
    pass


def max_attachment_bytes(cfg):
    return min(cfg['summary'].get('max_upload_bytes', MAX_ATTACHMENT_BYTES), MAX_ATTACHMENT_BYTES)


def team_sharing_enabled(cfg):
    security = cfg['security']
    return bool(cfg.get('demo') or security.get('team_reports_shared', security.get('team_daily_shared')) is True)


def validate_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        raise ValueError('日报日期应为 YYYY-MM-DD')
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        raise ValueError('日报日期不是有效的日历日期') from None
    return value


def fields_for_daily(fields):
    if not isinstance(fields, dict) or set(fields) != set(FIELDS):
        raise ValueError('日报必须包含今日完成、结果与证据、问题与阻塞、明日计划四个栏目')
    return {key: value.replace('\r\n', '\n') for key, value in validate_fields(fields).items()}


def markdown(name, day, fields):
    return f'# {name} · {day} 科研日报\n\n' + '\n\n'.join(
        f'## {title}\n\n{fields[key].strip()}' for key, title in FIELDS.items()) + '\n'


def template(name, day):
    validate_date(day)
    return markdown(name, day, dict.fromkeys(FIELDS, PLACEHOLDER))


def parse_report(text, name, day):
    validate_date(day)
    if not isinstance(text, str):
        raise ValueError('日报应为 UTF-8 Markdown 文本')
    lines = text.lstrip('\ufeff').replace('\r\n', '\n').strip().splitlines()
    if not lines or lines[0] != f'# {name} · {day} 科研日报':
        raise ValueError('日报标题与所选成员或日期不一致，请下载对应模板')
    if [line[3:] for line in lines[1:] if line.startswith('## ')] != list(FIELDS.values()):
        raise ValueError('四个二级标题必须完整、唯一并按日报模板顺序排列')
    out, current = {}, None
    by_title = {v: k for k, v in FIELDS.items()}
    for line in lines[1:]:
        if line.startswith('## '):
            current = by_title[line[3:]]
            out[current] = ''
        elif current is not None:
            out[current] += line + '\n'
        elif line.strip():
            raise ValueError('标题与第一个栏目之间不能添加额外内容')
    return fields_for_daily(out)


def document_fields(filename, document):
    """Extract locally, using the report's labels wherever it provides them."""
    extension = Path(filename).suffix.lower()
    if extension not in BODY_EXTENSIONS:
        raise ValueError('此格式可作为附件。请在线填写正文，或选择 Markdown、TXT、CSV、Word、Excel、PowerPoint 或可选中文字的 PDF。')
    try:
        text = intake.extract_document(filename, extension, document)['content'].lstrip('\ufeff')
    except (ValueError, OSError, BadZipFile, ParseError, PdfReadError):
        raise ValueError('无法读取正文，请核对编码和文件大小。扫描件和照片可作为附件，再在线补写正文。') from None
    if PLACEHOLDER in text:
        raise ValueError('请替换模板中的填写提示后再上传')
    by_title = {title: key for key, title in FIELDS.items()}
    sections = {key: [] for key in FIELDS}
    current = 'done'
    for line in text.splitlines():
        title, colon, content = line.strip().replace('：', ':', 1).partition(':')
        key = by_title.get(title.removeprefix('## ').strip())
        if key:
            current = key
            if colon and content.strip():
                sections[current].append(content.strip())
        else:
            # Keep document headings readable without making them new report sections.
            sections[current].append(re.sub(r'^#{1,2}(?=\s)', '###', line.lstrip()) if line.lstrip().startswith('#') else line)
    return fields_for_daily({key: '\n'.join(lines).strip() or '未说明' for key, lines in sections.items()})


def daily_paths(cfg, member, day):
    root = child(cfg['roots']['members'], member['id'], 'daily')
    day = validate_date(day)
    return child(root, day + '.md'), child(root, day)


def file_metadata(name, data):
    return {'name': name, 'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def store(cfg, member, day, text, attachments, original=None):
    """Commit one complete submission. Call while holding the existing write lock."""
    legacy, bundle = daily_paths(cfg, member, day)
    ordered = sorted(attachments, key=lambda attachment: attachment[0].casefold())
    metadata = {'attachments': [file_metadata(name, data) for name, data in ordered]}
    if original is not None:
        metadata['original'] = file_metadata(*original)
    limit = cfg['summary']['max_report_bytes']
    exists = legacy.exists() or bundle.exists()
    if exists:
        previous = read_text(legacy if legacy.exists() else child(bundle, 'report.md'), limit)
        previous_metadata = {'attachments': []}
        if not legacy.exists():
            previous_metadata = json.loads(read_text(child(bundle, 'metadata.json'), 16_384))
            previous_metadata.pop('team_visible', None)
        if previous != text or previous_metadata != metadata:
            raise DailyConflict('该成员当天已有不同的日报或附件，请联系维护人员更正')
        return True

    if not ordered and original is None:
        atomic_write(legacy, text)
        return False

    bundle.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.pending-', dir=bundle.parent) as path:
        staging = Path(path)
        atomic_write(child(staging, 'report.md'), text)
        if original is not None:
            atomic_write_bytes(child(staging, 'original'), original[1])
        for index, (_, data) in enumerate(ordered):
            atomic_write_bytes(child(staging, f'attachment-{index + 1}'), data)
        write_json(child(staging, 'metadata.json'), metadata)
        os.replace(staging, bundle)
    return False


def read_for_team(cfg, member, day, include_fields=True):
    legacy, bundle = daily_paths(cfg, member, day)
    legacy_exists = legacy.exists()
    if not legacy_exists and not bundle.exists():
        return None
    if not include_fields or not team_sharing_enabled(cfg):
        return {'date': day, 'fields': None, 'attachment_count': 0}
    metadata = {} if legacy_exists else json.loads(read_text(child(bundle, 'metadata.json'), 16_384))
    path = legacy if legacy_exists else child(bundle, 'report.md')
    text = read_text(path, cfg['summary']['max_report_bytes'])
    fields = parse_report(text, member['name'], day)
    payload = {'date': day, 'fields': fields, 'attachment_count': len(metadata.get('attachments', []))}
    if 'original' in metadata:
        payload['imported_body'] = True
    return payload
