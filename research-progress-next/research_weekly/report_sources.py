"""Resolve shared report downloads using registered members and fixed file layouts."""
import json
import re

from . import daily_reports, intake
from .core import ID, child, read_text, validate_week
from .members import registered_members


def _context(cfg, kind, uid, period):
    if not daily_reports.team_sharing_enabled(cfg):
        raise PermissionError('此入口尚未启用团队报告共享')
    if kind not in {'daily', 'weekly'}:
        raise ValueError('报告类型须为 daily 或 weekly')
    if not isinstance(uid, str) or not ID.fullmatch(uid):
        raise ValueError('成员 ID 格式无效')
    if kind == 'daily':
        daily_reports.validate_date(period)
    else:
        validate_week(period)
    member = next((entry for entry in registered_members(cfg) if entry['id'] == uid), None)
    if member is None:
        raise FileNotFoundError('成员未登记')
    if not child(cfg['roots']['members'], uid).is_dir():
        raise FileNotFoundError('成员目录不存在')
    return member


def _daily(cfg, member, day):
    legacy, bundle = daily_reports.daily_paths(cfg, member, day)
    attachments = []
    if legacy.is_file():
        return {'path': legacy, 'filename': day + '.md', 'label': '下载日报记录 Markdown', 'attachments': attachments}
    if not bundle.is_dir():
        raise FileNotFoundError('日报不存在')
    metadata = json.loads(read_text(child(bundle, 'metadata.json'), 16_384))
    if not isinstance(metadata, dict):
        raise ValueError('日报文件记录无效')
    entries = metadata.get('attachments', [])
    if not isinstance(entries, list) or len(entries) > daily_reports.MAX_ATTACHMENTS:
        raise ValueError('日报附件记录无效')
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise ValueError('日报附件记录无效')
        name = intake.safe_filename(entry.get('name'))
        path = child(bundle, f'attachment-{index}')
        if path.is_file():
            attachments.append({'path': path, 'name': name, 'index': index})
    original = metadata.get('original')
    original_path = child(bundle, 'original')
    if original is not None:
        if not isinstance(original, dict):
            raise ValueError('日报原件记录无效')
        name = intake.safe_filename(original.get('name'))
        if original_path.is_file():
            return {'path': original_path, 'filename': name, 'label': '下载日报原件', 'attachments': attachments}
    report = child(bundle, 'report.md')
    if not report.is_file():
        raise FileNotFoundError('日报记录不存在')
    return {'path': report, 'filename': day + '.md', 'label': '下载日报记录 Markdown', 'attachments': attachments}


def _weekly(cfg, member, week):
    upload = intake.load_status(cfg, member['id'], week)
    if upload:
        filename = intake.safe_filename(upload.get('original_filename'))
        extension = intake.extension_for(filename)
        if upload.get('extension') != extension:
            raise ValueError('周报原件格式与记录不一致')
        original = intake.original_path(cfg, member['id'], week, extension)
        if original.is_file():
            return {'path': original, 'filename': filename, 'label': '下载周报原件', 'attachments': []}
    report = child(cfg['roots']['members'], member['id'], 'reports', week + '.md')
    if not report.is_file():
        raise FileNotFoundError('周报不存在')
    return {'path': report, 'filename': week + '.md', 'label': '下载周报记录 Markdown', 'attachments': []}


def _record(cfg, kind, uid, period):
    member = _context(cfg, kind, uid, period)
    return _daily(cfg, member, period) if kind == 'daily' else _weekly(cfg, member, period)


def add_original_links(cfg, digest):
    """Resolve only originals that are readable through the team's existing report routes."""
    for source in (digest.get('document') or {}).get('sources', []):
        kind = source.get('kind')
        if kind not in {'daily', 'weekly'}:
            continue
        period = source.get('date' if kind == 'daily' else 'week')
        try:
            original = describe(cfg, kind, source['member_id'], period)
        except (OSError, ValueError):
            continue
        source.update(original_url=original['url'], original_label=original['label'],
                      attachments=original.get('attachments', []))
    return digest


def describe(cfg, kind, uid, period):
    record = _record(cfg, kind, uid, period)
    url = f'/progress/api/report-source/{kind}/{uid}/{period}'
    return {
        'url': url,
        'label': record['label'],
        'attachments': [{'name': attachment['name'], 'url': url + '/' + str(attachment['index'])}
                        for attachment in record['attachments']],
    }


def resolve(cfg, kind, uid, period, index=None):
    record = _record(cfg, kind, uid, period)
    if index is None:
        return {key: record[key] for key in ('path', 'filename')}
    if type(index) is not int:
        if not isinstance(index, str) or not re.fullmatch(r'[1-9][0-9]*', index):
            raise ValueError('附件编号无效')
        index = int(index)
    if index < 1:
        raise ValueError('附件编号无效')
    attachment = next((entry for entry in record['attachments'] if entry['index'] == index), None)
    if attachment is None:
        raise FileNotFoundError('附件不存在')
    return {'path': attachment['path'], 'filename': attachment['name']}
