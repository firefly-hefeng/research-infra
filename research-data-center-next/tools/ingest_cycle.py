"""One bounded rules cycle on the designated local coordinator; never approves."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ingestion


def cycle(worker, verify_limit=4, publish_limit=1):
    ingestion.require(type(verify_limit) is int and 1 <= verify_limit <= 4
                      and type(publish_limit) is int and 1 <= publish_limit <= 1,
                      'cycle_limits_outside_bounded_policy')
    if worker.meta('worker_enabled') is False:
        return {'mode': 'disabled', 'registered': [], 'verified': [], 'published': []}
    result = {'mode': 'active', 'registered': worker.scan(), 'verified': [], 'published': [], 'errors': []}
    # Only new jobs and interrupted verification are retried automatically.
    # Review, failed and incomplete publication require an operator's decision.
    for row in worker.connection.execute(
            "SELECT id FROM jobs WHERE status IN ('submitted','validating') ORDER BY updated_at,id LIMIT ?",
            (verify_limit,)).fetchall():
        try:
            result['verified'].append({'id': row['id'], 'status': worker.verify(row['id'])['status']})
        except (ingestion.IngestionError, OSError, ValueError) as exc:
            # A malformed submission or a known verification failure must not
            # occupy the automatic retry window forever. An actual process
            # termination leaves validating for a later bounded retry.
            job = worker.change(row['id'], 'failed', 'validation_exception_' + type(exc).__name__, approval=None)
            result['errors'].append({'id': row['id'], 'status': job['status'], 'error': type(exc).__name__})
    for row in worker.connection.execute(
            "SELECT id FROM jobs WHERE status IN ('ready','publishing') ORDER BY updated_at,id LIMIT ?",
            (publish_limit,)).fetchall():
        try:
            result['published'].append({'id': row['id'], 'status': worker.publish(row['id'])['status']})
        except (ingestion.IngestionError, OSError, ValueError) as exc:
            job = worker.job(row['id'])
            # A transient I/O interruption may reconcile an already-written
            # READY next cycle. A content/policy mismatch needs management and
            # must not repeatedly hash the same broken destination every run.
            if isinstance(exc, (ingestion.IngestionError, ValueError)) and job['status'] in ('ready', 'publishing'):
                job = worker.change(row['id'], 'review_required', 'publication_review_' + type(exc).__name__, approval=None)
            result['errors'].append({'id': row['id'], 'status': job['status'], 'error': type(exc).__name__})
    worker.heartbeat()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-db', type=Path, default=ingestion.DEFAULT_DB)
    args = parser.parse_args()
    try:
        with ingestion.Coordinator(args.state_db) as worker:
            print(json.dumps({'ok': True, **cycle(worker)}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc) if isinstance(exc, ingestion.IngestionError) else type(exc).__name__}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
