"""Seal an existing personal incoming directory; never upload or copy private files."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ingestion


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'status'))
    parser.add_argument('submission_directory', type=Path)
    args = parser.parse_args()
    try:
        result = getattr(ingestion, args.action if args.action == 'prepare' else 'client_status')(args.submission_directory)
        print(json.dumps({'ok': True, **result}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc) if isinstance(exc, ingestion.IngestionError) else type(exc).__name__}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
