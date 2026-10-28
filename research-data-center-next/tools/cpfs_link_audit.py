"""Offline symlink relocation audit; never reads a link target from the filesystem.

The manifest is streamed and only symlink records are retained. Full paths and
targets go to a private JSON report; stdout contains counts and status only.
``passed`` means a complete audit found no NEW relocation hazard. It does not
mean that historical external links, cycles, or unknown targets are usable.
"""
import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import posixpath
import tempfile


BASE = Path('/data/rmp/research-data-center/var/cpfs-migration-20261027')
ROOT_MAP = {
    '/data/datasets': '/data/share/datasets',
    '/data/models': '/data/share/models',
}
MAX_LINKS = 40


def normalize(path):
    """Linux-style absolute lexical normalization; no filesystem lookups."""
    if not isinstance(path, str) or not path.startswith('/') or '\0' in path:
        raise ValueError('Expected an absolute POSIX path without NUL')
    return posixpath.normpath('/' + path.lstrip('/'))


def within(path, root):
    return path == root or path.startswith(root + '/')


def mapped(path):
    for old, new in ROOT_MAP.items():
        if within(path, old):
            return new + path[len(old):]
    return path


def lexical_target(link_path, target):
    if not isinstance(target, str) or not target or '\0' in target:
        raise ValueError('Invalid symlink target')
    return normalize(target if target.startswith('/') else
                     posixpath.join(posixpath.dirname(link_path), target))


def resolve_manifest(path, links, roots, aliases=None, max_links=MAX_LINKS):
    """Resolve known link prefixes after lexical normalization, bounded to 40.

    Unknown internal paths may be files OR broken links; this function does not
    decide which. An external path ends resolution without probing that path.
    New-view aliases model the two explicitly planned old-root compatibility
    symlinks, not arbitrary host symlinks.
    """
    aliases = aliases or {}
    allowed = tuple(roots) + tuple(aliases)
    current = normalize(path)
    seen = set()
    trace = []
    while True:
        if current in seen:
            return dict(status='cycle', path=current, hops=len(trace), trace=trace)
        seen.add(current)
        if not any(within(current, root) for root in allowed):
            return dict(status='external_unchecked', path=current,
                        hops=len(trace), trace=trace)

        selected = None
        parts = current.strip('/').split('/')
        for index in range(1, len(parts) + 1):
            prefix = '/' + '/'.join(parts[:index])
            if prefix in aliases:
                selected = (prefix, aliases[prefix], 'compatibility_alias')
                break
            if prefix in links:
                selected = (prefix, links[prefix], 'manifest_symlink')
                break
        if selected is None:
            return dict(status='internal_availability_unchecked', path=current,
                        hops=len(trace), trace=trace)
        if len(trace) >= max_links:
            return dict(status='depth_limit', path=current,
                        hops=len(trace), trace=trace)
        prefix, target, kind = selected
        suffix = current[len(prefix):].lstrip('/')
        replacement = lexical_target(prefix, target)
        current = normalize(posixpath.join(replacement, suffix))
        trace.append(dict(link=prefix, target=target, kind=kind))


def audit_rows(rows, max_links=MAX_LINKS):
    links = {}
    errors = []
    rows_read = 0
    for number, row in enumerate(rows, 1):
        rows_read = number
        try:
            if not isinstance(row, dict):
                raise ValueError('Manifest row is not an object')
            if row.get('kind') != 'symlink':
                continue
            root = row.get('root')
            relative = row.get('relative_path')
            if root not in ROOT_MAP or not isinstance(relative, str) or not relative:
                raise ValueError('Unknown root or missing relative path')
            if relative.startswith('/') or '\0' in relative:
                raise ValueError('Invalid relative path')
            path = normalize(root + '/' + relative)
            if path == root or not within(path, root):
                raise ValueError('Manifest link path escapes its source root')
            target = row.get('target')
            lexical_target(path, target)
            if path in links:
                raise ValueError('Duplicate manifest symlink path')
            links[path] = target
        except (TypeError, ValueError) as exc:
            errors.append(dict(row=number, error=str(exc), record=row))

    new_links = {mapped(path): target for path, target in links.items()}
    counts = dict(manifest_rows=rows_read, symlinks=len(links), relative_links=0,
                  absolute_internal_alias_dependencies=0,
                  absolute_external_node_dependencies=0,
                  relative_external_targets_before=0,
                  relative_external_targets_after=0,
                  preexisting_cycles=0, preexisting_depth_limits=0,
                  new_cycles=0, new_depth_limits=0,
                  relative_relocation_hazards=0,
                  other_relocation_hazards=0, errors=len(errors))
    details = []
    relative_hazards = []
    other_hazards = []
    existing_cycles = []
    limits = []
    for path, target in links.items():
        new_path = mapped(path)
        old_lexical = lexical_target(path, target)
        new_lexical = lexical_target(new_path, target)
        relative = not target.startswith('/')
        old_internal = any(within(old_lexical, root) for root in ROOT_MAP)
        record = dict(path=path, target=target)
        reasons = []
        if relative:
            counts['relative_links'] += 1
            record['kind'] = 'relative'
            record['old_lexical_target'] = old_lexical
            record['new_lexical_target'] = new_lexical
            record['expected_new_lexical_target'] = mapped(old_lexical)
            if not old_internal:
                counts['relative_external_targets_before'] += 1
            if not any(within(new_lexical, root) for root in ROOT_MAP.values()):
                counts['relative_external_targets_after'] += 1
            if mapped(old_lexical) != new_lexical:
                reasons.append('relative_lexical_target_changes_after_relocation')
        elif old_internal:
            record['kind'] = 'absolute_internal_requires_old_root_alias'
            counts['absolute_internal_alias_dependencies'] += 1
        else:
            record['kind'] = 'absolute_external_node_dependency'
            counts['absolute_external_node_dependencies'] += 1
            # Existing external absolute targets are deliberately NOT followed.
            # A target inside the planned new roots can acquire new semantics
            # after publication, so model that case from the manifest only.
            if not any(within(old_lexical, root) for root in ROOT_MAP.values()):
                details.append(record)
                continue

        before = resolve_manifest(path, links, ROOT_MAP, max_links=max_links)
        after = resolve_manifest(new_path, new_links, ROOT_MAP.values(),
                                 aliases=ROOT_MAP, max_links=max_links)
        record['before'] = before
        record['after'] = after
        old_bad = before['status'] in ('cycle', 'depth_limit')
        new_bad = after['status'] in ('cycle', 'depth_limit')
        if before['status'] == 'cycle':
            counts['preexisting_cycles'] += 1
            existing_cycles.append(dict(path=path, resolution=before))
        if before['status'] == 'depth_limit':
            counts['preexisting_depth_limits'] += 1
            limits.append(dict(path=path, view='before', resolution=before))
        if after['status'] == 'cycle' and not old_bad:
            counts['new_cycles'] += 1
            reasons.append('new_manifest_cycle')
        if after['status'] == 'depth_limit' and not old_bad:
            counts['new_depth_limits'] += 1
            reasons.append('new_resolution_depth_limit')
            limits.append(dict(path=path, view='after', resolution=after))
        if not old_bad and not new_bad and mapped(before['path']) != after['path']:
            reasons.append('manifest_chain_target_changes_after_relocation')
        if reasons:
            record['hazard_reasons'] = reasons
            (relative_hazards if relative else other_hazards).append(record)
        details.append(record)

    counts['relative_relocation_hazards'] = len(relative_hazards)
    counts['other_relocation_hazards'] = len(other_hazards)
    complete = not errors
    return dict(
        schema_version='1.0',
        observed_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        complete=complete,
        passed=complete and not relative_hazards and not other_hazards,
        passed_definition='Complete manifest audit with no detected NEW relocation '
                          'hazards; does NOT assert link availability or portability.',
        scope='offline_manifest_only_no_target_filesystem_access',
        roots=ROOT_MAP,
        new_view_requires_aliases=ROOT_MAP,
        max_symlink_expansions=max_links,
        counts=counts,
        relative_relocation_hazards=relative_hazards,
        other_relocation_hazards=other_hazards,
        preexisting_internal_cycles=existing_cycles,
        resolution_limits=limits,
        symlinks=details,
        errors=errors,
        limitations=[
            'Lexical normalization and known-manifest link-prefix simulation only; '
            'not a kernel realpath or filesystem availability check.',
            'Unlisted host symlinks, external targets, access permissions, and '
            'historical broken links are not inspected.',
            'Preexisting external absolute links and preexisting cycles/depth limits '
            'alone do not fail this audit.',
            'Absolute internal links require the two old-root compatibility aliases '
            'on every host where those links will be used.',
        ],
    )


def read_rows(path):
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        for line in stream:
            # JSON parse errors abort the audit rather than silently dropping links.
            yield json.loads(line)


def manifest_identity(path):
    s = os.stat(path)
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def manifest_digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_private_report(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix='.link-audit-', suffix='.tmp', dir=path.parent)
        temporary = Path(name)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def public_summary(report):
    return dict(complete=report['complete'], passed=report['passed'],
                passed_scope='no_new_relocation_hazards_not_all_links_usable',
                counts=report['counts'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=BASE / 'source-files.jsonl.gz')
    parser.add_argument('--output', type=Path, default=BASE / 'link-audit.json')
    args = parser.parse_args(argv)
    execution_failed = False
    try:
        before = manifest_identity(args.manifest)
        report = audit_rows(read_rows(args.manifest))
        report['source_manifest_sha256'] = manifest_digest(args.manifest)
        if manifest_identity(args.manifest) != before:
            raise RuntimeError('Manifest changed while auditing or hashing')
    except Exception as exc:
        execution_failed = True
        report = dict(schema_version='1.0', complete=False, passed=False,
                      observed_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                      counts=dict(errors=1),
                      errors=[dict(error_type=type(exc).__name__, error=str(exc))])
    report['manifest'] = str(args.manifest)
    try:
        # Replace a stale successful report even when this audit cannot finish.
        write_private_report(args.output, report)
    except Exception as exc:
        # No private paths/targets or exception messages are exposed on stdout.
        print(json.dumps(dict(complete=False, passed=False, error_type=type(exc).__name__)))
        return 2
    print(json.dumps(public_summary(report), ensure_ascii=False))
    if execution_failed:
        return 2
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
