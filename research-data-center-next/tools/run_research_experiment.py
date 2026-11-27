"""Run the approved protocols as the current OS user using a member-exported direction context."""
import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

try:
    from .agent_client import ENDPOINTS
    from .research_experiment import build_plan, execute_plan
except ImportError:
    from agent_client import ENDPOINTS
    from research_experiment import build_plan, execute_plan


def export_sources(snapshot):
    if snapshot.get("schema_version") != "1.0" or snapshot.get("mode") != "offline_snapshot":
        raise ValueError("请输入从成员平台导出的方向上下文 JSON。")
    by_url = {row["url"]: row["data"] for row in snapshot["sources"].values()
              if row.get("status") == "ok" and isinstance(row.get("data"), dict)}
    return {name: by_url[url] for name in ("directions", "library", "research", "papers", "progress")
            for url in ["/papers/api/catalog" if name == "papers" and "/papers/api/catalog" in by_url else ENDPOINTS[name]]
            if url in by_url}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="方向名字、方向 ID 或研究主题")
    parser.add_argument("--snapshot", type=Path, required=True, help="已登录平台导出的本地上下文")
    parser.add_argument("--output", type=Path, required=True, help="新的电子实验记录 JSON，保留原件")
    parser.add_argument("--noncommercial-member", action="store_true", help="在既有组权限内启用获准的非商业研究协议")
    args = parser.parse_args(argv)
    try:
        if args.snapshot.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("上下文超过 16 MiB 的读取预算。")
        if args.output.exists():
            raise ValueError("目标实验记录已存在，请选择另一个路径。")
        raw = args.snapshot.read_bytes()
        src = export_sources(json.loads(raw))
        plan = build_plan(args.query, src, allow_noncommercial=args.noncommercial_member)
        run = execute_plan(plan, src, allow_noncommercial=args.noncommercial_member)
        record = {"snapshot_sha256": hashlib.sha256(raw).hexdigest(), "plan": plan, "run": run}
        # Publish without overwriting an existing result or exposing a partial JSON file.
        with tempfile.NamedTemporaryFile(dir=args.output.parent, delete=False) as out:
            temporary = Path(out.name)
        try:
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.link(temporary, args.output)
        finally:
            temporary.unlink()
        print(f"{run['status']} · {run['fingerprint']} · {args.output}")
        return 0 if run["status"] == "completed" else 2
    except (OSError, KeyError, ValueError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
