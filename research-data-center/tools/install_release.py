"""Install a verified application bundle only within this application's directory.

Preserves runtime state and creates a recoverable source backup before replacing
files. Does not touch datasets, models, incoming, permissions or running services.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ROOTS = {'static', 'docs', 'tests', 'deploy', 'tools', 'data'}
ALLOWED_FILES = {'catalog.py', 'server.py', 'progress_proxy.py', 'README.md', '.gitignore', 'release-manifest.json'}


def validate_name(name):
    parts = PurePosixPath(name).parts
    if not parts or '\\' in name or name.startswith('/') or '..' in parts or ':' in name:
        raise ValueError('Unsafe archive path')
    if len(parts) == 1:
        if name not in ALLOWED_FILES:
            raise ValueError('Unexpected top-level file')
    elif parts[0] not in ALLOWED_ROOTS or any(part.startswith('.') for part in parts):
        raise ValueError('Unexpected archive directory')
    target = (ROOT / name).resolve()
    if not target.is_relative_to(ROOT) or target.is_relative_to((ROOT / 'var').resolve()):
        raise ValueError('Path escapes application source')
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    (ROOT / 'var').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='release-stage-', dir=ROOT / 'var') as scratch:
        stage = Path(scratch)
        with tarfile.open(args.archive, 'r:gz') as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            if len(set(names)) != len(names) or sum(member.size for member in members) > 100_000_000:
                raise ValueError('Duplicate paths or oversized release')
            for member in members:
                validate_name(member.name)
                if not member.isfile():
                    raise ValueError('Only regular files are accepted')
                output = stage / member.name
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, output.open('wb') as destination:
                    shutil.copyfileobj(source, destination)
        manifest = json.loads((stage / 'release-manifest.json').read_text(encoding='utf-8'))
        if set(names) != set(manifest) | {'release-manifest.json'}:
            raise ValueError('Manifest does not exactly cover release')
        for name, digest in manifest.items():
            if hashlib.sha256((stage / name).read_bytes()).hexdigest() != digest:
                raise ValueError('Release checksum mismatch: ' + name)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = ROOT / 'var' / 'release-backups' / stamp
        backup.mkdir(parents=True)
        replaced, created = [], []
        try:
            for name in names:
                target = validate_name(name)
                if target.exists():
                    previous = backup / name
                    previous.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, previous)
                    replaced.append(name)
                else:
                    created.append(name)
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + '.release-new')
                shutil.copyfile(stage / name, temporary)
                os.chmod(temporary, 0o600)
                os.replace(temporary, target)
        except BaseException:
            for name in replaced:
                shutil.copy2(backup / name, validate_name(name))
            for name in created:
                validate_name(name).unlink(missing_ok=True)
            raise
        (backup / 'installed-files.json').write_text(json.dumps({'replaced': replaced, 'created': created}), encoding='utf-8')
        print(json.dumps({'installed_files': len(names), 'backup': str(backup), 'runtime_untouched': True}))


if __name__ == '__main__':
    main()
