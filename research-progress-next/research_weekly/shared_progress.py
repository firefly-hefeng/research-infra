"""Member-visible progress documents, read through the same shared-report setting as the methods index."""
import hashlib
import json

from flask import Blueprint, abort, current_app, jsonify, request

from . import directions, progress_digest
from .core import child
from .daily_reports import team_sharing_enabled
from .lab_review_json import project
from .lab_review_page import render, shared_review


blueprint = Blueprint('shared_progress', __name__)


def shared_config():
    cfg = current_app.config['RESEARCH']
    if not team_sharing_enabled(cfg):
        abort(403, '团队报告共享尚未启用')
    return cfg


@blueprint.get('/api/directions')
def direction_index():
    items, unavailable = directions.load_directions(shared_config())
    return jsonify(items=items, unavailable=unavailable)


@blueprint.get('/api/directions/<direction_id>')
def direction_detail(direction_id):
    return jsonify(directions.read_direction(shared_config(), direction_id))


@blueprint.get('/api/progress-digest')
def progress():
    return jsonify(progress_digest.read(shared_config()))


@blueprint.get('/api/lab-review')
def review():
    cfg = shared_config()
    formats = request.args.getlist('format')
    if formats and (len(formats) != 1 or formats[0] not in ('html', 'json')):
        abort(400, '复盘格式应为 html 或 json')
    version = request.args.get('version', 'reviewed')
    if version not in ('reviewed', 'auto'):
        abort(404)
    team = cfg['roots']['team']
    try:
        published = shared_review(child(team, 'lab-review.json'))
    except PermissionError:
        abort(403)
    automatic = None
    if published.get('editorial_review'):
        try:
            candidate = shared_review(child(team, 'lab-review-auto.json'))
        except (FileNotFoundError, PermissionError, ValueError, KeyError):
            pass
        else:
            encoded = json.dumps(published, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
            if candidate.get('based_on_review') == hashlib.sha256(encoded).hexdigest():
                automatic = candidate
    if version == 'auto' and automatic is None:
        abort(404)
    document = automatic if version == 'auto' else published
    companion = 'reviewed' if version == 'auto' else 'auto' if automatic else None
    if formats == ['json']:
        return jsonify(project(document, version, companion))
    return render(document, companion=companion)
