"""Read-only acceptance of one relocated storage entry on the source host.

Run as a member with the expected access. The receipt confirms pathname
compatibility for that observer. Test file manifests and access for other
accounts separately before writing the destination back to the ledger.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import socket
import stat


def check_alias(old, destination, library):
    paths = [Path(p) for p in (old, destination, library)]
    if any(not p.is_absolute() or '..' in p.parts for p in paths):
        raise ValueError('absolute_paths_without_parent_traversal_required')
    old, destination, library = paths
    if old == destination or not destination.is_relative_to(library):
        raise ValueError('distinct_old_and_destination_under_library_required')
    root = library.resolve(strict=True)
    target = destination.resolve(strict=True)
    if not root.is_dir() or not target.is_relative_to(root):
        raise ValueError('destination_outside_resolved_library')
    if target != root / destination.relative_to(library):
        raise ValueError('destination_must_be_the_canonical_entry')
    target_info = target.stat()
    directory = stat.S_ISDIR(target_info.st_mode)
    if not (directory or stat.S_ISREG(target_info.st_mode)):
        raise ValueError('regular_file_or_directory_required')
    # An older deployment linked the library root rather than every child entry.
    if not any(path.is_symlink() for path in (old, *old.parents)):
        raise ValueError('old_route_has_no_symbolic_link')
    if not old.samefile(target) or old.resolve(strict=True) != target:
        raise ValueError('old_route_points_elsewhere')
    required_access = os.R_OK | (os.X_OK if directory else 0)
    if not os.access(old, required_access) or not os.access(destination, required_access):
        raise ValueError('observer_access_failed')
    observation = {
        'kind': 'directory' if directory else 'file',
        'device': target_info.st_dev,
        'inode': target_info.st_ino,
        'mode': format(stat.S_IMODE(target_info.st_mode), '04o'),
    }
    if directory:
        with os.scandir(old) as entries:
            next(entries, None)
    else:
        with old.open('rb') as stream:
            stream.read(1)
        observation['size_bytes'] = target_info.st_size
    return observation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record-id', required=True)
    parser.add_argument('--old', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--library', required=True, type=Path)
    args = parser.parse_args()
    receipt = {'record_id': args.record_id, 'host': socket.gethostname(),
               'observed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
               'old': str(args.old), 'destination': str(args.destination),
               'library': str(args.library), 'status': 'unverified'}
    try:
        receipt['target'] = check_alias(args.old, args.destination, args.library)
        receipt['status'] = 'verified'
    except (OSError, ValueError, RuntimeError) as error:
        receipt['error'] = str(error)
    print(json.dumps(receipt, ensure_ascii=False))
    return int(receipt['status'] != 'verified')


if __name__ == '__main__':
    raise SystemExit(main())
