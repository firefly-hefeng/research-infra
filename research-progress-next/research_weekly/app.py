"""Login-free report intake. Original member reports are never served over HTTP."""
import json
from flask import Flask, abort, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from .core import (PROJECT, ID, atomic_write, child, date_range, digest, init_dirs,
                   load_config, locked, md_name, member, now, read_text,
                   report_markdown, validate_week, week_id)
from .reports import parse_report, template, validate_fields
from . import daily_reports
from .members import NameExists, registered_members, register


def create_app(config_path=None):
    cfg = load_config(config_path)
    # Starting the web service must not provision missing member directories.
    init_dirs(cfg)
    app = Flask(__name__, static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=100_000, RESEARCH=cfg)

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
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if cfg['security'].get('https', cfg['security'].get('secure_cookies', False)):
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    @app.errorhandler(Exception)
    def error(exc):
        if isinstance(exc, HTTPException):
            return jsonify(error=exc.description), exc.code
        if isinstance(exc, FileNotFoundError):
            return jsonify(error='文件不存在'), 404
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
        if name not in {'app.js', 'style.css'}:
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
                       max_report_bytes=cfg['summary']['max_report_bytes'], template_version=1)

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

    @app.post('/api/daily/uploads')
    def upload_daily():
        if request.is_json:
            data = request.get_json()
            if not isinstance(data, dict) or set(data) != {'member_id', 'date', 'fields'}:
                abort(400, '日报 JSON 只接受 member_id、date、fields')
            uid, day = data['member_id'], daily_reports.validate_date(data['date'])
            fields = daily_reports.fields_for_daily(data['fields'])
            with locked(cfg):
                return store_daily(eligible(uid), day, fields)
        if request.mimetype != 'multipart/form-data':
            abort(415, '请使用 application/json 或 multipart/form-data')
        if set(request.form) != {'member_id', 'date'} or set(request.files) != {'file'} or any(len(request.form.getlist(k)) != 1 for k in request.form) or len(request.files.getlist('file')) != 1:
            abort(400, '日报文件上传只接受 member_id、date 和一个 file')
        uid, day = request.form['member_id'], daily_reports.validate_date(request.form['date'])
        f = request.files['file']
        md_name(f.filename)
        data = f.stream.read(cfg['summary']['max_report_bytes'] + 1)
        if len(data) > cfg['summary']['max_report_bytes']:
            abort(413, '日报超出大小限制')
        with locked(cfg):
            m = eligible(uid)
            return store_daily(m, day, daily_reports.parse_report(data.decode('utf-8'), m['name'], day))

    def store_daily(m, day, fields):
        text = daily_reports.markdown(m['name'], day, fields)
        if len(text.encode()) > cfg['summary']['max_report_bytes']:
            abort(413, '日报超出大小限制')
        target = child(cfg['roots']['members'], m['id'], 'daily', day+'.md')
        duplicate = target.exists()
        if duplicate and read_text(target, cfg['summary']['max_report_bytes']) != text:
            abort(409, '该成员当天已有不同内容的日报，无登录上传不允许覆盖；请联系维护人员更正')
        if not duplicate:
            atomic_write(target, text)
        return jsonify(ok=True, duplicate=duplicate, member_id=m['id'], date=day,
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
        md_name(f.filename)
        data = f.stream.read(cfg['summary']['max_report_bytes'] + 1)
        if len(data) > cfg['summary']['max_report_bytes']:
            abort(413, '周报超出大小限制')
        with locked(cfg):
            m = eligible(uid)
            fields = parse_report(data.decode('utf-8'), m['name'], week)
            return store(m, week, fields)

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
                items.append({k: doc[k] for k in ("week", "date_range", "submitted", "expected", "generated_at", "engine_label", "revision")})
        return jsonify(items=items)

    @app.get("/api/team/<week>")
    def team_doc(week):
        validate_week(week)
        with locked(cfg):
            doc = json.loads(read_text(child(cfg["roots"]["team"], "weekly", week + ".json"), 2_000_000))
        return jsonify(doc)

    @app.get("/api/knowledge")
    def knowledge():
        items = []
        for p in sorted(cfg["roots"]["knowledge"].glob("*.md")):
            text = read_text(child(cfg["roots"]["knowledge"], md_name(p.name)))
            title = next((l.lstrip("# ") for l in text.splitlines() if l.startswith("# ")), p.stem)
            excerpt = next((l for l in text.splitlines() if l.strip() and not l.startswith("#")), "团队共享的入门资料")
            items.append({"name": p.name, "title": title, "excerpt": excerpt[:120]})
        return jsonify(items=items)

    @app.get("/api/knowledge/<name>")
    def knowledge_doc(name):
        return jsonify(name=name, content=read_text(child(cfg["roots"]["knowledge"], md_name(name))))


    return app
