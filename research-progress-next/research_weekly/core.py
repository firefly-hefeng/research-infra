import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from zoneinfo import ZoneInfo

PROJECT = Path(__file__).resolve().parents[1]
ID = re.compile(r"[a-z][a-z0-9_-]{1,31}\Z")
FIELDS = {"done": "本周完成", "results": "结果与证据", "blockers": "问题与阻塞", "next": "下周计划"}


def no_symlinks(path):
    path = Path(os.path.abspath(path))
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError("文件路径不能包含符号链接")
    return path


def load_config(path=None):
    path = Path(path or os.environ.get("RESEARCH_CONFIG", PROJECT / "config.demo.json")).absolute()
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["config_path"] = str(path)
    ZoneInfo(cfg["timezone"])
    ids = [m["id"] for m in cfg["members"]]
    if len(set(ids)) != len(ids) or not all(ID.fullmatch(i) for i in ids):
        raise ValueError("成员 ID 必须唯一，且为 2–32 位小写字母、数字、下划线或连字符")
    for member in cfg["members"]:
        if not isinstance(member.get("name"), str) or not member["name"].strip() or len(member["name"]) > 80:
            raise ValueError("成员姓名不能为空或过长")
    roots = {}
    for name in ("members", "team", "knowledge", "state"):
        p = Path(cfg["paths"][name]).expanduser()
        roots[name] = no_symlinks(p if p.is_absolute() else path.parent / p)
    for key, a in roots.items():
        for other, b in roots.items():
            if key != other and (a == b or a in b.parents):
                raise ValueError("个人、公共、知识和系统状态目录必须彼此隔离，不能嵌套")
    cfg["roots"] = roots
    if not cfg.get("demo") and cfg["security"].get("transport") != "ssh-tunnel" and not cfg["security"].get("https", cfg["security"].get("secure_cookies", False)):
        raise ValueError("正式环境须使用 HTTPS 反向代理或显式设置 ssh-tunnel 回环部署")
    return cfg


def init_dirs(cfg, provision_members=False):
    for root in cfg["roots"].values():
        no_symlinks(root).mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
    for m in cfg["members"] if provision_members else []:
        for part in ("reports",):
            no_symlinks(cfg["roots"]["members"] / m["id"] / part).mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, part in (("team", "weekly"), ("state", "jobs"), ("state", "history")):
        no_symlinks(cfg["roots"][name] / part).mkdir(exist_ok=True, mode=0o700)


def now(cfg):
    return dt.datetime.now(ZoneInfo(cfg["timezone"]))


def week_id(day):
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


def validate_week(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-W\d{2}", value):
        raise ValueError("周次应为 YYYY-Www，例如 2026-W42")
    dt.date.fromisocalendar(int(value[:4]), int(value[-2:]), 1)
    return value


def select_week(cfg, value):
    if value in (None, "previous"):
        return week_id(now(cfg).date() - dt.timedelta(days=7))
    if value == "current":
        return week_id(now(cfg).date())
    return validate_week(value)


def date_range(week):
    validate_week(week)
    start = dt.date.fromisocalendar(int(week[:4]), int(week[-2:]), 1)
    return [start.isoformat(), (start + dt.timedelta(days=6)).isoformat()]


def member(cfg, uid):
    return next((m for m in cfg["members"] if m["id"] == uid), None)


def child(root, *parts):
    root = no_symlinks(root)
    path = no_symlinks(root.joinpath(*parts))
    if path == root or root not in path.parents:
        raise ValueError("无效路径")
    return path


def md_name(name):
    if not isinstance(name, str) or len(name) > 120 or name.startswith(".") or not re.fullmatch(r"[\w\- .\u4e00-\u9fff]+\.md", name) or ".." in name:
        raise ValueError("仅支持不含路径的 Markdown 文件名")
    return name


def read_text(path, limit=65536):
    path = no_symlinks(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as f:
        data = f.read(limit + 1)
    if len(data) > limit:
        raise ValueError("文件超过大小限制")
    return data.decode("utf-8")


def atomic_write(path, text):
    path = no_symlinks(path)
    no_symlinks(path.parent).mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_json(path, data):
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


@contextlib.contextmanager
def locked(cfg, name="files"):
    p = child(cfg["roots"]["state"], f"{name}.lock")
    fd = os.open(p, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def report_markdown(name, week, fields):
    return f"# {name} · {week} 科研周报\n\n" + "\n\n".join(f"## {title}\n\n{fields[k].strip()}" for k, title in FIELDS.items()) + "\n"


def report_fields(text):
    out = dict.fromkeys(FIELDS, "")
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = next((k for k, title in FIELDS.items() if title == line[3:].strip()), None)
        elif current:
            out[current] += line + "\n"
    return {k: v.strip() for k, v in out.items()}
