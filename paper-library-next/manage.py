#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
from paperlib.library import Library

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / 'papers'


def main():
    p = argparse.ArgumentParser(description='Paper Library · 固定目录论文管理')
    p.add_argument('--root', default=os.environ.get('PAPER_ROOT', str(DEFAULT_ROOT)))
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('init')
    sub.add_parser('import-root', help='复制根目录 PDF 到 inbox，保留原件')
    sub.add_parser('scan')
    sub.add_parser('list')
    sub.add_parser('migrate-titles', help='停服后将旧哈希归档目录迁移为论文题目，保留数据库备份')
    extract = sub.add_parser('extract')
    extract.add_argument('id')
    extract_insight = sub.add_parser('extract-insight', help='按阅读顺序提取导读依据，不修改原卡片正文缓存')
    extract_insight.add_argument('id')
    commit = sub.add_parser('commit')
    commit.add_argument('id')
    commit.add_argument('card', help='卡片 JSON 路径')
    insight = sub.add_parser('commit-insight', help='校验并保存独立论文导读，不重分类或移动 PDF')
    insight.add_argument('id')
    insight.add_argument('insight', help='导读 JSON 路径')
    batch = sub.add_parser('import-insights', help='逐项校验并导入 <论文ID>.json 导读文件')
    batch.add_argument('folder')
    batch.add_argument('--check', action='store_true', help='仅验证并记录日志，不保存导读')
    sub.add_parser('run', help='按整理设置调用 Agent / API 整理当前队列')
    serve = sub.add_parser('serve')
    serve.add_argument('--host', default=os.environ.get('PAPER_HOST', '127.0.0.1'))
    serve.add_argument('--port', default=int(os.environ.get('PAPER_PORT', '4186')), type=int)
    args = p.parse_args()
    library = Library(args.root)
    if args.command == 'init':
        result = {'root': str(library.root), 'inbox': str(library.root / 'inbox')}
    elif args.command == 'import-root':
        result = {'copied': library.bootstrap(), 'scan': library.scan()}
    elif args.command == 'scan':
        result = library.scan()
    elif args.command == 'list':
        result = library.papers()
    elif args.command == 'migrate-titles':
        result = library.migrate_title_directories()
    elif args.command == 'extract':
        print(library.extract(args.id))
        return
    elif args.command == 'extract-insight':
        from paperlib.insights import source_text
        print(source_text(library, args.id))
        return
    elif args.command == 'commit':
        result = library.commit(args.id, json.loads(Path(args.card).read_text()))
    elif args.command == 'commit-insight':
        from paperlib.insights import read_insight
        result = library.commit_insight(args.id, read_insight(args.insight))
    elif args.command == 'import-insights':
        from paperlib.insights import import_insights
        result = import_insights(library, args.folder, check=args.check)
    elif args.command == 'run':
        from paperlib.worker import run_batch
        result = run_batch(library)
    else:
        from paperlib.server import serve
        serve(library, args.host, args.port)
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == 'import-insights' and result['failed']:
        raise SystemExit(1)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, FileNotFoundError, KeyError, BlockingIOError) as exc:
        raise SystemExit(str(exc))
