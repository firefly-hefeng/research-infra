"""Explicit single-host rules coordinator. No daemon or scheduled work is installed."""
import argparse
import dataclasses
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ingestion


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-db', type=Path, default=ingestion.DEFAULT_DB)
    parser.add_argument('--max-bytes', type=int, default=10 * 1024 ** 3)
    parser.add_argument('--max-files', type=int, default=100000)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('scan')
    sub.add_parser('status')
    sub.add_parser('published-assets')
    enabled = sub.add_parser('enabled')
    enabled.add_argument('value', choices=('true', 'false'))
    for action in ('verify', 'publish', 'plan', 'approve'):
        command = sub.add_parser(action)
        command.add_argument('job_id')
        if action in ('plan', 'approve'):
            command.add_argument('--kind', choices=('dataset', 'model'), required=True)
            command.add_argument('--resource-id', required=True)
            command.add_argument('--version', required=True)
        if action == 'approve':
            command.add_argument('--digest', required=True)
    args = parser.parse_args()
    try:
        if args.action == 'status':
            result = ingestion.snapshot(args.state_db)
        elif args.action == 'published-assets':
            result = {'assets': ingestion.published_assets(args.state_db)}
        else:
            ingestion.require(args.max_bytes > 0 and args.max_files > 0, 'positive_policy_limits_required')
            policy = dataclasses.replace(ingestion.Policy(), max_bytes=args.max_bytes, max_files=args.max_files,
                                         max_entries=args.max_files * 2)
            with ingestion.Coordinator(args.state_db, policy) as worker:
                if args.action == 'enabled':
                    worker.set_meta('worker_enabled', args.value == 'true')
                    worker.connection.commit()
                    result = {'worker_enabled': args.value == 'true'}
                elif args.action == 'scan':
                    result = {'registered': worker.scan()}
                elif args.action == 'approve':
                    result = worker.approve(args.job_id, args.digest, args.kind, args.resource_id, args.version)
                elif args.action == 'plan':
                    result = worker.plan(args.job_id, args.kind, args.resource_id, args.version)
                else:
                    result = getattr(worker, args.action)(args.job_id)
                if 'id' in result:
                    job = result
                    result = {key: job[key] for key in ('id', 'status', 'reason_code', 'content_digest', 'updated_at')}
                    for field in ('plan', 'approval', 'publication'):
                        if job.get(field):
                            result[field] = json.loads(job[field])
        print(json.dumps({'ok': True, **result}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc) if isinstance(exc, ingestion.IngestionError) else type(exc).__name__}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
