"""Team report intake behind the portal login; shared originals use fixed routes."""
from datetime import date
import json
from pathlib import Path
from flask import Flask, abort, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException
from .core import (PROJECT, ID, atomic_write, child, date_range, digest, init_dirs,
                   load_config, locked, md_name, member, now, read_text,
                   report_markdown, validate_week, week_id)
from .reports import parse_report, template, validate_fields
from . import daily_reports, directions, intake, team_activity, progress_digest, report_sources
from .members import NameExists, registered_members, register
from .lab_review_json import project as shared_review_json
from .research_agent_api import agent as research_agent
from .direction_methods import blueprint as direction_methods


def create_app(config_path=None):
    cfg = load_config(config_path)
    # Starting the web service must not provision missing member directories.
    init_dirs(cfg)
    app = Flask(__name__, static_folder=None)
    app.register_blueprint(research_agent)
    app.register_blueprint(direction_methods)
    app.config.update(MAX_CONTENT_LENGTH=cfg['summary'].get('max_upload_bytes', 20 * 1024 * 1024) + 100_000,
                      RESEARCH=cfg)

    @app.before_request
    def protect():
        if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            origin = request.headers.get('Origin')
            if origin and origin not in cfg['security']['allowed_origins']:
                abort(403, '不允许的请求来源')
            if request.headers.get('X-Requested-With') != 'ResearchWeekly':
                abort(403, '上传请求需包含 X-Requested-With: ResearchWeekly')

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers.setdefault('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cfg['security'].get('https', cfg['security'].get('secure_cookies', False)):
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    @app.errorhandler(Exception)
    def error(exc):
        if isinstance(exc, HTTPException):
            return jsonify(error=exc.description), exc.code
        if isinstance(exc, FileNotFoundError):
            return jsonify(error='文件不存在'), 404
        if isinstance(exc, PermissionError):
            return jsonify(error='此入口的团队报告共享尚未启用'), 403
        if isinstance(exc, UnicodeDecodeError):
            return jsonify(error='文件必须使用 UTF-8 编码'), 400
        if isinstance(exc, ValueError):
            return jsonify(error=str(exc)), 400
        app.logger.error('Request failed: %s', type(exc).__name__)
        return jsonify(error='操作失败，请联系维护人员'), 500

    @app.get('/')
    def index():
        return send_from_directory(PROJECT / 'web', 'index.html')

    @app.get('/assets/<name>')
    def assets(name):
        if name not in {'app.js', 'style.css', 'activity.js', 'activity.css', 'digest.js', 'digest.css', 'lab-review.css', 'direction-methods.css', 'd3.v7.min.js', 'D3-LICENSE', 'rhythm.js', 'rhythm.css'}:
            abort(404)
        return send_from_directory(PROJECT / 'web', name)

    @app.get('/healthz')
    def health():
        return jsonify(status='ok')

    def eligible(uid):
        if not isinstance(uid, str) or not ID.fullmatch(uid):
            abort(400, '成员 ID 格式无效')
        m = next((m for m in registered_members(cfg) if m['id'] == uid), None)
        if not m or not child(cfg['roots']['members'], uid).is_dir():
            abort(403, '成员未登记或对应文件夹不存在，请联系维护人员')
        return m

    @app.get('/api/public')
    def public():
        members = []
        for m in registered_members(cfg):
            try:
                if child(cfg['roots']['members'], m['id']).is_dir():
                    members.append(m)
            except ValueError:
                continue
        today = now(cfg).date()
        current = week_id(today)
        return jsonify(team_name=cfg['team_name'], demo=cfg.get('demo', False),
                       members=members, week=current, date=today.isoformat(), daily_enabled=True,
                       registration_enabled=True, timezone=cfg['timezone'], portal_url=cfg.get('portal_url'),
                       max_report_bytes=cfg['summary']['max_report_bytes'],
                       daily_team_sharing=daily_reports.team_sharing_enabled(cfg),
                       max_daily_attachments=daily_reports.MAX_ATTACHMENTS,
                       max_daily_attachment_bytes=daily_reports.max_attachment_bytes(cfg),
                       max_upload_bytes=cfg['summary'].get('max_upload_bytes', 20 * 1024 * 1024), template_version=1)

    @app.post('/api/members')
    def register_name():
        if not request.is_json:
            abort(415, '姓名登记请使用 application/json')
        data = request.get_json()
        if not isinstance(data, dict) or set(data) != {'name'}:
            abort(400, '姓名登记只接受 name')
        try:
            m = register(cfg, data['name'])
        except NameExists as exc:
            abort(409, str(exc))
        return jsonify(ok=True, member=m), 201

    @app.get('/api/daily-template')
    def daily_template():
        m = eligible(request.args.get('member_id'))
        day = daily_reports.validate_date(request.args.get('date'))
        return jsonify(markdown=daily_reports.template(m['name'], day), filename=day+'.md', template_version=1)

    def check_daily_sharing(value):
        if type(value) is not bool:
            abort(400, 'team_visible 必须为布尔值')
        if value and not daily_reports.team_sharing_enabled(cfg):
            abort(403, '此部署的日报正文共享未启用')

    @app.post('/api/daily/uploads')
    def upload_daily():
        if request.is_json:
            data = request.get_json()
            required = {'member_id', 'date', 'fields'}
            if not isinstance(data, dict) or not required <= data.keys() <= required | {'team_visible'}:
                abort(400, '日报 JSON 接受 member_id、date、fields 和可选 team_visible')
            check_daily_sharing(data.get('team_visible', False))
            uid, day = data['member_id'], daily_reports.validate_date(data['date'])
            fields = daily_reports.fields_for_daily(data['fields'])
            with locked(cfg):
                return store_daily(eligible(uid), day, fields, [])
        if request.mimetype != 'multipart/form-data':
            abort(415, '请使用 application/json 或 multipart/form-data')
        required = {'member_id', 'date'}
        if (not required <= request.form.keys() <= required | {'fields', 'team_visible'}
                or not request.files.keys() <= {'file', 'attachments'}
                or any(len(request.form.getlist(key)) != 1 for key in request.form)):
            abort(400, '日报上传字段无效')
        uid, day = request.form['member_id'], daily_reports.validate_date(request.form['date'])
        share = request.form.get('team_visible', 'false')
        if share not in {'true', 'false'}:
            abort(400, 'team_visible 必须为 true 或 false')
        check_daily_sharing(share == 'true')
        report_files = request.files.getlist('file')
        if len(report_files) + ('fields' in request.form) != 1:
            abort(400, '日报正文需要一个文件或一组 fields')
        remaining = daily_reports.max_attachment_bytes(cfg)
        fields, text, original = None, None, None
        if report_files:
            report = report_files[0]
            name = intake.safe_filename(report.filename)
            extension = Path(name).suffix.lower()
            if extension not in daily_reports.BODY_EXTENSIONS:
                abort(415, '此格式可作为附件。请选择支持的正文文档或在线填写。')
            is_markdown = extension in {'.md', '.markdown'}
            limit = cfg['summary']['max_report_bytes'] if is_markdown else remaining
            data = report.stream.read(limit + 1)
            if len(data) > limit:
                abort(413, '日报文件超出大小限制')
            if is_markdown:
                text = data.decode('utf-8')
            else:
                remaining -= len(data)
                fields = daily_reports.document_fields(name, data)
                original = (name, data)
        else:
            fields = daily_reports.fields_for_daily(json.loads(request.form['fields']))
        files = request.files.getlist('attachments')
        if len(files) > daily_reports.MAX_ATTACHMENTS:
            abort(413, f'日报最多可上传 {daily_reports.MAX_ATTACHMENTS} 个附件')
        names, attachments = set(), []
        for attachment in files:
            name = intake.safe_filename(attachment.filename)
            if name.casefold() in names:
                abort(400, '同一日报的附件名称不能重复')
            names.add(name.casefold())
            data = attachment.stream.read(remaining + 1)
            if len(data) > remaining:
                abort(413, '日报原件和附件总大小超出限制')
            if not data:
                abort(400, '日报附件不能为空')
            remaining -= len(data)
            attachments.append((name, data))
        with locked(cfg):
            m = eligible(uid)
            if text is not None:
                fields = daily_reports.parse_report(text, m['name'], day)
            return store_daily(m, day, fields, attachments, original)

    def store_daily(m, day, fields, attachments, original=None):
        text = daily_reports.markdown(m['name'], day, fields)
        if len(text.encode()) > cfg['summary']['max_report_bytes']:
            abort(413, '日报超出大小限制')
        try:
            duplicate = daily_reports.store(cfg, m, day, text, attachments, original)
        except daily_reports.DailyConflict as exc:
            abort(409, str(exc))
        return jsonify(ok=True, duplicate=duplicate, member_id=m['id'], date=day,
                       week=week_id(date.fromisoformat(day)),
                       team_visible=daily_reports.team_sharing_enabled(cfg), attachment_count=len(attachments),
                       sha256=digest(text), template_version=1), (200 if duplicate else 201)

    @app.get('/api/report-template')
    def report_template():
        m = eligible(request.args.get('member_id'))
        week = validate_week(request.args.get('week'))
        return jsonify(markdown=template(m['name'], week), filename=week+'.md', template_version=1)

    @app.post('/api/uploads')
    def upload_report():
        if request.is_json:
            data = request.get_json()
            if not isinstance(data, dict) or set(data) != {'member_id', 'week', 'fields'}:
                abort(400, 'JSON 只接受 member_id、week、fields')
            uid, week = data['member_id'], validate_week(data['week'])
            fields = validate_fields(data['fields'])
            with locked(cfg):
                m = eligible(uid)
                return store(m, week, fields)
        if request.mimetype != 'multipart/form-data':
            abort(415, '请使用 application/json 或 multipart/form-data')
        if set(request.form) != {'member_id', 'week'} or set(request.files) != {'file'} or any(len(request.form.getlist(k)) != 1 for k in request.form) or len(request.files.getlist('file')) != 1:
            abort(400, '文件上传只接受 member_id、week 和一个 file')
        uid, week = request.form['member_id'], validate_week(request.form['week'])
        f = request.files['file']
        maximum = cfg['summary'].get('max_upload_bytes', 20 * 1024 * 1024)
        data = f.stream.read(maximum + 1)
        if len(data) > maximum:
            abort(413, '周报文件超出上传大小限制')
        with locked(cfg):
            m = eligible(uid)
            try:
                status, duplicate = intake.store_upload(cfg, m, week, f.filename, data, f.mimetype)
            except intake.UploadConflict as exc:
                abort(409, str(exc))
        return jsonify(ok=True, duplicate=duplicate, member_id=m['id'], week=week,
                       sha256=status.get('normalized_sha256', status['sha256']),
                       upload_sha256=status['sha256'], summary_status=status['status'],
                       status_detail=status.get('status_detail', '')), (200 if duplicate else 201)

    @app.get('/api/upload-status')
    def upload_status():
        m = eligible(request.args.get('member_id'))
        week = validate_week(request.args.get('week'))
        record = intake.load_status(cfg, m['id'], week)
        if record:
            return jsonify(intake.public_status(record))
        canonical = child(cfg['roots']['members'], m['id'], 'reports', week + '.md')
        if canonical.exists():
            return jsonify(member_id=m['id'], week=week, status='ready', status_detail='标准周报已进入团队汇总')
        abort(404, '该成员本周尚未上传周报')

    def store(m, week, fields):
        text = report_markdown(m['name'], week, fields)
        if len(text.encode()) > cfg['summary']['max_report_bytes']:
            abort(413, '周报超出大小限制')
        target = child(cfg['roots']['members'], m['id'], 'reports', week+'.md')
        duplicate = target.exists()
        if duplicate and read_text(target, cfg['summary']['max_report_bytes']) != text:
            abort(409, '该成员本周已有不同内容的周报，无登录上传不允许覆盖；请联系维护人员更正')
        if not duplicate:
            atomic_write(target, text)
        return jsonify(ok=True, duplicate=duplicate, member_id=m['id'], week=week,
                       sha256=digest(text), template_version=1), (200 if duplicate else 201)

    @app.get("/api/team")
    def team_list():
        items = []
        with locked(cfg):
            for path in sorted(child(cfg["roots"]["team"], "weekly").glob("*.json"), reverse=True):
                validate_week(path.stem)
                doc = json.loads(read_text(path, 2_000_000))
                item = {k: doc[k] for k in ("week", "date_range", "submitted", "expected", "generated_at", "engine_label", "revision")}
                item.update(received=doc.get('received', doc['submitted']), pending=len(doc.get('pending', [])))
                items.append(item)
        return jsonify(items=items)

    @app.get("/api/team/<week>")
    def team_doc(week):
        validate_week(week)
        with locked(cfg):
            doc = json.loads(read_text(child(cfg["roots"]["team"], "weekly", week + ".json"), 2_000_000))
        return jsonify(doc)

    @app.get('/api/team/activity')
    def team_week_activity():
        week = request.args.get('week', week_id(now(cfg).date()))
        uid, day = request.args.get('member'), request.args.get('date')
        report = request.args.get('report')
        if uid is not None and not ID.fullmatch(uid):
            abort(400, '成员 ID 格式无效')
        if report is not None and (report != 'weekly' or not uid or day is not None):
            abort(400, '查询周报须指定成员，日报日期请单独查询')
        if day is not None:
            daily_reports.validate_date(day)
        return jsonify(team_activity.collect(cfg, week, uid, day, report == 'weekly'))

    @app.get('/api/progress-digest')
    def shared_progress_digest():
        result = progress_digest.read(cfg)
        result['has_lab_review'] = False
        if daily_reports.team_sharing_enabled(cfg):
            from .lab_review_page import shared_review
            try:
                shared_review(child(cfg['roots']['team'], 'lab-review.json'))
            except (FileNotFoundError, PermissionError, ValueError, KeyError):
                pass
            else:
                result['has_lab_review'] = True
        return jsonify(report_sources.add_original_links(cfg, result))

    @app.get('/api/lab-review')
    def shared_lab_review():
        from .lab_review_page import render, shared_review
        from .lab_review import revision
        if not daily_reports.team_sharing_enabled(cfg):
            raise PermissionError
        formats=request.args.getlist('format')
        if formats and (len(formats)!=1 or formats[0] not in ('html','json')):
            abort(400, '复盘格式应为 html 或 json')
        path = child(cfg['roots']['team'], 'lab-review.json')
        document = shared_review(path)
        version = request.args.get('version', 'reviewed')
        if version not in ('reviewed','auto'):
            abort(404)
        automatic = None
        if document.get('editorial_review'):
            try:
                candidate = shared_review(child(path.parent,'lab-review-auto.json'))
            except (FileNotFoundError,PermissionError,ValueError,KeyError):
                pass
            else:
                if candidate.get('based_on_review') == revision(document):
                    automatic = candidate
        if version == 'auto':
            if not automatic:
                abort(404)
            document,companion=automatic,'reviewed'
        else:
            companion='auto' if automatic else None
        if formats==['json']:
            return jsonify(shared_review_json(document,version,companion))
        return render(document, companion=companion)

    @app.get('/api/report-source/<kind>/<uid>/<period>')
    @app.get('/api/report-source/<kind>/<uid>/<period>/<int:index>')
    def report_source_file(kind, uid, period, index=None):
        source = report_sources.resolve(cfg, kind, uid, period, index)
        response = send_file(source['path'], download_name=source['filename'], as_attachment=True,
                             mimetype='application/octet-stream', conditional=True)
        response.headers['Content-Security-Policy'] = "default-src 'none'; frame-ancestors 'none'; sandbox"
        return response

    @app.get("/api/directions")
    def direction_list():
        items, unavailable = directions.load_directions(cfg)
        return jsonify(items=items, unavailable=unavailable)

    @app.get("/api/directions/<direction_id>")
    def direction_doc(direction_id):
        return jsonify(directions.read_direction(cfg, direction_id))

    @app.get("/api/knowledge")
    def knowledge():
        items = []
        configured = {p.name: p for p in cfg["roots"]["knowledge"].glob("*.md")}
        for name in ("README.md", "02-周报怎么写.md"):
            configured.setdefault(name, PROJECT / "deploy" / "knowledge" / name)
        for name, path in sorted(configured.items(), key=lambda item: (item[0] != "README.md", item[0])):
            text = read_text(child(path.parent, md_name(name)))
            title = next((l.lstrip("# ") for l in text.splitlines() if l.startswith("# ")), path.stem)
            excerpt = next((l for l in text.splitlines() if l.strip() and not l.startswith("#")), "团队共享的入门资料")
            items.append({"name": name, "title": title, "excerpt": excerpt[:120]})
        return jsonify(items=items)

    @app.get("/api/knowledge/<name>")
    def knowledge_doc(name):
        path = child(cfg["roots"]["knowledge"], md_name(name))
        if name in {"README.md", "02-周报怎么写.md"} and not path.exists():
            path = PROJECT / "deploy" / "knowledge" / name
        return jsonify(name=name, content=read_text(path))


    return app
