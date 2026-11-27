"""Direction-to-experiment entry point for the existing signed-in team workspace."""
import fcntl
import hashlib
import json
import os
import re
import sys
import threading
import uuid
from datetime import datetime, timezone
from http.client import HTTPConnection, HTTPException
from pathlib import Path

from flask import Blueprint, abort, current_app, jsonify, request, send_from_directory

from . import daily_reports, directions, progress_digest, report_sources
from .core import PROJECT, no_symlinks, write_json

agent = Blueprint("research_agent", __name__)
RUN_ID = re.compile(r"[a-f0-9]{32}\Z")
CATALOGS = {"research": (8765, "/api/platform/research"), "library": (8765, "/api/platform/library"),
            "papers": (4186, "/api/catalog")}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def sources_for(cfg):
    items, unavailable = directions.load_directions(cfg)
    sources = {"directions": {"items": items, "unavailable": unavailable},
               "progress": report_sources.add_original_links(cfg, progress_digest.read(cfg))}
    missing = []
    for name, (port, path) in CATALOGS.items():
        conn = HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            if response.status != 200 or "application/json" not in (response.getheader("Content-Type") or ""):
                raise ValueError()
            payload = response.read(16 * 1024 * 1024 + 1)
            if len(payload) > 16 * 1024 * 1024:
                raise ValueError()
            value = json.loads(payload)
            if not isinstance(value, dict):
                raise ValueError()
            sources[name] = value
        except (OSError, HTTPException, ValueError):
            missing.append(name)
        finally:
            conn.close()
    return sources, missing


def records_dir():
    cfg = current_app.config["RESEARCH"]
    if not daily_reports.team_sharing_enabled(cfg):
        abort(403, "此工作区尚未启用团队共享")
    path = no_symlinks(cfg["roots"]["state"] / "research-experiments")
    path.mkdir(exist_ok=True, mode=0o700)
    return path


def read_record(path):
    return json.loads(no_symlinks(path).read_text(encoding="utf-8"))


def try_lock(root):
    fd = os.open(root / ".worker.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def run_experiment(cfg, path, entry, fd):
    try:
        from .experiment_kernel import research_experiment as kernel
        sources, missing = sources_for(cfg)
        entry["missing_sources"] = missing
        entry["reproduction"] = {
            "python": sys.version.split()[0], "protocol_version": kernel.VERSION,
            "code_sha256": {Path(mod.__file__).name: hashlib.sha256(Path(mod.__file__).read_bytes()).hexdigest()
                            for mod in (kernel, kernel.audio, kernel.dc)},
            "sources_read_at": timestamp(),
            "research_reviewed_at": (sources.get("research") or {}).get("reviewed_at"),
            "progress_revision": ((sources.get("progress") or {}).get("document") or {}).get("revision"),
        }
        plan = kernel.build_plan(entry["query"], sources)
        entry["plan"] = plan
        if plan["protocols"]:
            entry["experiment"] = kernel.execute_plan(plan, sources)
            entry["status"] = entry["experiment"]["status"]
        else:
            entry["status"] = "no_protocol"
    except ValueError as exc:
        entry.update(status="unavailable", message=str(exc))
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Research experiment failed (run %s)", entry["id"])
        entry.update(status="failed", message="实验未完成，可重新提交此方向。")
    finally:
        try:
            entry["finished_at"] = timestamp()
            write_json(path, entry)
        finally:
            os.close(fd)


def resolve_record(path):
    entry = read_record(path)
    if entry["status"] == "running":
        fd = try_lock(path.parent)
        if fd is not None:
            try:
                recover(path.parent)
                entry = read_record(path)
            finally:
                os.close(fd)
    return entry


def recover(root):
    # Called with the exclusive worker lock. A running record here lost its worker.
    marker = root / ".active"
    if marker.exists():
        previous = read_record(marker)
        ident = previous.get("id", "")
        if RUN_ID.fullmatch(ident) and (root / (ident + ".json")).is_file():
            path = root / (ident + ".json")
            entry = read_record(path)
            if entry["status"] == "running":
                entry.update(status="interrupted", finished_at=timestamp(), message="服务重启中断了这次实验，可重新运行。")
                write_json(path, entry)


@agent.get("/research-agent")
def research_agent_page():
    records_dir()
    return send_from_directory(PROJECT / "web", "research-agent.html")


@agent.get("/research-agent-assets/<name>")
def agent_asset(name):
    if name not in {"research-agent.js", "research-agent.css"}:
        abort(404)
    return send_from_directory(PROJECT / "web", name)


@agent.get("/api/research-experiments/<ident>")
def read_experiment(ident):
    root = records_dir()
    path = root / (ident + ".json")
    if not RUN_ID.fullmatch(ident) or not path.is_file():
        abort(404, "未找到此实验记录")
    return jsonify(resolve_record(path))


@agent.get("/api/research-experiments")
def recent_experiments():
    root = records_dir()
    files = sorted((p for p in root.glob("*.json") if RUN_ID.fullmatch(p.stem)),
                   key=lambda p: p.stat().st_mtime_ns, reverse=True)[:12]
    keys = ("id", "query", "status", "started_at", "finished_at")
    items = []
    for r in map(resolve_record, files):
        title = (r.get("plan") or {}).get("direction", {}).get("title") or r["query"]
        items.append({**{k: r[k] for k in keys if k in r}, "title": title})
    return jsonify(items=items)


@agent.post("/api/research-experiments")
def start_experiment():
    root = records_dir()
    if request.content_length is None or request.content_length > 2048:
        abort(413, "研究方向请求最多 2 KiB")
    data = request.get_json()
    if not isinstance(data, dict) or set(data) - {"query", "request_id"}:
        abort(400, "请提交研究方向 query，可附带 request_id")
    query = data.get("query")
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 180 or any(ord(c) < 32 for c in query):
        abort(400, "请输入 1 至 180 字的研究方向")
    ident = data.get("request_id", uuid.uuid4().hex)
    if not isinstance(ident, str) or not RUN_ID.fullmatch(ident):
        abort(400, "request_id 应为 32 位小写十六进制")
    path = root / (ident + ".json")
    query = query.strip()
    def existing():
        entry = read_record(path)
        if entry["query"] != query:
            abort(409, "这个请求编号已用于另一个方向")
        return jsonify(entry), 200
    if path.exists():
        return existing()
    fd = try_lock(root)
    if fd is None:
        if path.exists():
            return existing()
        return jsonify(error="另一项实验正在运行，请稍后重试"), 429, {"Retry-After": "5"}
    try:
        recover(root)
        if path.exists():
            return existing()
        entry = {"id": ident, "query": query, "status": "running", "started_at": timestamp()}
        write_json(root / ".active", {"id": ident})
        write_json(path, entry)
        threading.Thread(target=run_experiment, args=(current_app.config["RESEARCH"], path, entry.copy(), fd),
                         name="research-experiment", daemon=True).start()
        fd = None
        return jsonify(entry), 202
    finally:
        if fd is not None:
            os.close(fd)
