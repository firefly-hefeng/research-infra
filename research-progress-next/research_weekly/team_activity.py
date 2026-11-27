"""Live report feeds, weekly navigation and the selected member's report."""
import datetime as dt
import json

from . import daily_reports, intake, report_sources
from .core import child, date_range, digest, locked, now, read_text, week_id
from .members import registered_members
from .reports import parse_report


UNREADABLE = (OSError, ValueError, TypeError, KeyError, AttributeError)


def _daily_record(cfg, member, day, sharing):
    try:
        submitted = daily_reports.read_for_team(cfg, member, day, include_fields=False)
    except UNREADABLE:
        return None
    if submitted is None:
        return None
    record = {'date': day, 'fields': None, 'attachment_count': 0}
    if sharing:
        try:
            record = daily_reports.read_for_team(cfg, member, day)
        except UNREADABLE:
            record['unavailable'] = True
    return record


def _source_links(cfg, kind, uid, period):
    try:
        original = report_sources.describe(cfg, kind, uid, period)
    except UNREADABLE:
        return {}
    return {'original_url': original['url'], 'original_label': original['label'],
            'attachments': original.get('attachments', [])}


def _limit_feed_content(cfg, records):
    remaining = cfg['summary'].get('max_total_bytes', 524_288)
    for record in records:
        if record['fields'] is None:
            continue
        size = len(json.dumps(record['fields'], ensure_ascii=False).encode())
        if size > remaining:
            record.update(fields=None, content_deferred=True)
        else:
            remaining -= size


def _weekly_timetable(cfg, first, members, member_id, sharing):
    weeks = [week_id(first - dt.timedelta(weeks=offset)) for offset in range(4)]
    records = []
    for member in sorted(members, key=lambda person: (person['name'], person['id'])):
        uid = member['id']
        if member_id is not None and member_id != uid:
            continue
        for week in weeks:
            try:
                exists = child(cfg['roots']['members'], uid, 'reports', week + '.md').is_file()
                if not exists:
                    upload = intake.load_status(cfg, uid, week)
                    if upload:
                        filename = intake.safe_filename(upload.get('original_filename'))
                        extension = intake.extension_for(filename)
                        exists = upload.get('extension') == extension and intake.original_path(cfg, uid, week, extension).is_file()
            except UNREADABLE:
                continue
            if not exists:
                continue
            links = _source_links(cfg, 'weekly', uid, week) if sharing else {}
            records.append({'member_id': uid, 'member_name': member['name'], 'week': week,
                            'url': '#team?week=' + week + '&member=' + uid + '&report=weekly',
                            'readable': bool(links), **links})
    return {'weeks': weeks, 'records': records}


def collect(cfg, week, member_id=None, selected_date=None, weekly_detail=False):
    start, _ = date_range(week)
    first = dt.date.fromisoformat(start)
    days = [(first + dt.timedelta(days=offset)).isoformat() for offset in range(7)]
    if selected_date is not None and selected_date not in days:
        raise ValueError('日报日期须在所选周次内')

    people = []
    detail = None
    weekly = None
    daily_records, weekly_reports = [], []
    sharing = daily_reports.team_sharing_enabled(cfg)
    with locked(cfg):
        source = child(cfg['roots']['team'], 'weekly', week + '.json')
        published = json.loads(read_text(source, 2_000_000)) if source.exists() else {}
        published_sources = {row['id']: row.get('source_sha256') for row in published.get('members', [])}
        members = registered_members(cfg)
        timetable = _weekly_timetable(cfg, first, members, member_id, sharing)
        for member in members:
            uid = member['id']
            upload_error = False
            try:
                upload = intake.load_status(cfg, uid, week)
            except UNREADABLE:
                upload, upload_error = None, True
            try:
                weekly_path = child(cfg['roots']['members'], uid, 'reports', week + '.md')
                has_weekly = weekly_path.is_file()
            except UNREADABLE:
                weekly_path, has_weekly = None, False
            fields = None
            if has_weekly:
                reviewed_hash = published_sources.get(uid)
                needs_text = reviewed_hash or sharing
                text = None
                if needs_text:
                    try:
                        text = read_text(weekly_path, cfg['summary']['max_report_bytes'])
                    except UNREADABLE:
                        pass
                current_hash = digest(text) if text is not None and reviewed_hash else None
                weekly_status = 'published' if reviewed_hash and current_hash == reviewed_hash else 'ready'
                if text is not None and sharing:
                    try:
                        fields = parse_report(text, member['name'], week)
                    except UNREADABLE:
                        fields = None
                    if fields and weekly_detail and uid == member_id:
                        weekly = {'fields': fields}
            elif upload:
                weekly_status = upload['status']
            elif upload_error:
                weekly_status = 'failed'
            elif uid in published_sources:
                weekly_status = 'published'
            else:
                weekly_status = 'missing'
            if (member_id is None or member_id == uid) and (has_weekly or upload or upload_error):
                record = {'member_id': uid, 'member_name': member['name'], 'week': week,
                          'fields': fields, 'status': weekly_status,
                          'url': '#team?week=' + week + '&member=' + uid + '&report=weekly'}
                if not sharing:
                    record.update(unavailable=True, shared=False)
                elif upload_error or (has_weekly and fields is None):
                    record['unavailable'] = True
                else:
                    record.update(_source_links(cfg, 'weekly', uid, week))
                weekly_reports.append(record)
            submitted = []
            for day in days:
                record = _daily_record(cfg, member, day, sharing)
                if record is None:
                    continue
                submitted.append(day)
                if uid == member_id and selected_date == day:
                    detail = record.copy()
                if member_id is not None and member_id != uid:
                    continue
                entry = {'member_id': uid, 'member_name': member['name'], 'date': day,
                         'fields': record['fields'], 'attachment_count': record['attachment_count'],
                         'imported_body': record.get('imported_body', False),
                         'url': '#team?week=' + week + '&member=' + uid + '&date=' + day}
                if not sharing:
                    entry.update(unavailable=True, shared=False)
                elif record.get('unavailable'):
                    entry['unavailable'] = True
                else:
                    entry.update(_source_links(cfg, 'daily', uid, day))
                daily_records.append(entry)
            people.append({'id': uid, 'name': member['name'], 'weekly_status': weekly_status,
                           'weekly_readable': sharing and has_weekly, 'days': submitted})

    daily_records.sort(key=lambda record: (record['member_name'], record['member_id']))
    daily_records.sort(key=lambda record: record['date'], reverse=True)
    weekly_reports.sort(key=lambda record: (record['member_name'], record['member_id']))
    _limit_feed_content(cfg, [*daily_records, *weekly_reports])

    return {
        'week': week, 'current_week': week_id(now(cfg).date()), 'dates': days, 'members': people,
        'weekly_revision': published.get('revision'), 'weekly_generated_at': published.get('generated_at'),
        'selected_daily': detail, 'selected_weekly': weekly,
        'daily_records': daily_records, 'weekly_reports': weekly_reports,
        'weekly_timetable': timetable,
    }
