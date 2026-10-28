#!/usr/bin/env python3
"""Validate private CPFS receipts and publish a minimal, immutable evidence bundle.

This is NOT a copy/cutover/cleanup operator. Production CLI locations, host and
snapshot digests are fixed; no production files are written by the default check.
Tests may inject a Policy into prepare_bundle using temporary fixture roots.
"""
import argparse
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import tempfile

try:
    from . import path_migration as migration
except ImportError:
    import path_migration as migration


PROJECT = Path('/data/rmp/research-data-center')
BASE = PROJECT / 'var/cpfs-migration-20261027'
HOST = 'iZuf6jc6bqdgxmhcci4k3wZ'
STAGE = '/data/share/.rdc-migration-20261027'
MIGRATION_ID = 'cpfs-20261027'
BASELINE_SHA256 = '5c05f387cf328e27367380a28db9fad9e8a92fd9e301349babfa4eaf9d903871'
MANIFEST_SHA256 = 'abf15d245255a9d8927ce6078dee9160c81dc7b88e1c0ae5bfdd0469990f4220'
BASELINE_REF = 'data/sources/catalog-pre-migration.json'
REPORT_NAMES = ('copy', 'verification', 'cutover', 'cleanup', 'preflight')
NAMES = ('models', 'datasets')
OBSERVATION_FIELDS = ('host', 'path', 'realpath', 'observed_at', 'account', 'exists',
                      'readable', 'kind', 'owner', 'mode', 'mtime_ns', 'uid', 'gid')


class PublishError(ValueError):
    """Safe machine-readable error code, without private receipt contents."""


class Policy:
    def __init__(self, project=PROJECT, base=BASE, host=HOST, stage=STAGE,
                 baseline_sha256=BASELINE_SHA256, manifest_sha256=MANIFEST_SHA256,
                 record_count=228, path_count=221,
                 root_counts=None):
        self.project = Path(project).absolute()
        self.base = Path(base).absolute()
        self.host = host
        self.stage = stage
        self.baseline_sha256 = baseline_sha256
        self.manifest_sha256 = manifest_sha256
        self.record_count = record_count
        self.path_count = path_count
        self.root_counts = root_counts or {'datasets': 2220141, 'models': 234}


def require(condition, code):
    if not condition:
        raise PublishError(code)


def timestamp(value, code):
    try:
        migration.timestamp(value, code)
        return dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (TypeError, ValueError):
        raise PublishError(code + '_invalid_time') from None


def integer(value, code, minimum=0):
    require(type(value) is int and value >= minimum, code + '_invalid_integer')
    return value


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def signature(path):
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def guarded_path(root, relative, exists=True):
    """Reject symlinks in every component, including existing output files."""
    relative = Path(relative)
    require(not relative.is_absolute() and '..' not in relative.parts, 'unsafe_relative_path')
    require(root.exists() and root.is_dir() and root.resolve() == root, 'unsafe_root')
    path = root
    for part in relative.parts:
        path = path / part
        require(not path.is_symlink(), 'symlink_receipt_or_output_refused')
    if exists:
        require(path.is_file() and path.resolve().is_relative_to(root), 'required_regular_file_missing')
    else:
        require(path.resolve().is_relative_to(root), 'output_outside_project')
    return path


class Reader:
    def __init__(self, policy):
        self.policy = policy
        self.snapshots = {}
        self.hashes = {}

    def read(self, name, project=False, limit=16 * 1024 * 1024):
        root = self.policy.project if project else self.policy.base
        path = guarded_path(root, name)
        before = signature(path)
        require(before[2] <= limit, 'receipt_exceeds_size_limit')
        data = path.read_bytes()
        require(signature(path) == before, 'receipt_changed_while_reading')
        self.snapshots[path] = before
        self.hashes[name] = sha256(data)
        return data

    def document(self, name, project=False, limit=16 * 1024 * 1024):
        try:
            value = json.loads(self.read(name, project, limit))
        except (UnicodeError, json.JSONDecodeError):
            raise PublishError('receipt_invalid_json') from None
        require(isinstance(value, dict), 'receipt_must_be_object')
        return value

    def digest(self, name):
        path = guarded_path(self.policy.base, name)
        before = signature(path)
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        require(signature(path) == before, 'receipt_changed_while_hashing')
        self.snapshots[path] = before
        self.hashes[name] = digest.hexdigest()
        return digest.hexdigest(), before[2]

    def stable(self):
        for path, before in self.snapshots.items():
            require(not path.is_symlink() and signature(path) == before, 'input_changed_before_publication')


def mount(value):
    try:
        return migration.validate_mount(value)
    except ValueError:
        raise PublishError('cpfs_mount_mismatch') from None


def inode(value):
    require(isinstance(value, dict), 'root_inode_receipt_required')
    result = {key: integer(value.get(key), 'root_' + key) for key in ('dev', 'ino', 'mode', 'uid', 'gid')}
    require(stat.S_ISDIR(result['mode']), 'destination_root_not_directory')
    require(result['uid'] == 0 and result['gid'] == 0, 'destination_root_owner_changed')
    return result


def audit(reader, name, policy, location=None):
    value = reader.document(name)
    require(value.get('host') == policy.host, 'audit_host_mismatch')
    timestamp(value.get('observed_at'), 'audit')
    if location:
        require(value.get('location') == location and value.get('passed') is True
                and value.get('errors') == [], 'source_revalidation_failed')
        require(value.get('expected_entries') == policy.root_counts
                and value.get('actual_entries') == policy.root_counts, 'source_revalidation_count_mismatch')
    else:
        require(value.get('visibility') == 'local_host_only_inode_match'
                and value.get('processes') == [] and value.get('errors') == []
                and value.get('mount_aliases') == [], 'source_usage_not_clear')
    return {'status': 'passed', 'observed_at': value['observed_at'],
            'receipt_sha256': reader.hashes[name],
            'scope': 'original_inode_metadata' if location else 'local_host_inode_usage'}


def validate_observations(value, journal, journal_hash, baseline, policy, binding):
    require(value.get('schema_version') == '1.0' and value.get('migration_id') == MIGRATION_ID,
            'observation_migration_mismatch')
    require(value.get('host') == policy.host and value.get('account') == 'rmp'
            and value.get('observer_uid') == 1011, 'ordinary_observer_identity_required')
    require(value.get('complete') is True and value.get('errors') == [], 'entry_observation_failed')
    require(value.get('baseline_sha256') == policy.baseline_sha256
            and value.get('cutover_state_sha256') == journal_hash
            and value.get('switched_at') == journal['switched_at']
            and value.get('cutover_phase') == journal['phase'], 'observation_binding_stale')
    start = timestamp(value.get('started_at'), 'observation_start')
    end = timestamp(value.get('observed_at'), 'observation_end')
    final_time = journal['cleaned_at'] if journal['phase'] == 'cleaned' else journal['switched_at']
    require(timestamp(final_time, 'journal_final') <= start <= end, 'post_cutover_observation_required')
    checked_mount = mount(value.get('mount'))
    required = {migration.destination_path(asset['path']) for asset in baseline['assets']}
    rows = value.get('observations')
    require(isinstance(rows, list) and len(rows) == policy.path_count, 'all_destination_entries_required')
    seen, clean = set(), []
    for row in rows:
        require(isinstance(row, dict), 'observation_row_invalid')
        path = row.get('path')
        require(path in required and path not in seen, 'duplicate_or_unknown_destination_entry')
        seen.add(path)
        root = migration.ROOT_PAIRS[migration.logical_root(path)][1]
        require(row.get('exists') is True and row.get('readable') is True
                and row.get('kind') in ('file', 'directory') and row.get('account') == 'rmp'
                and row.get('observer_uid') == 1011 and row.get('host') == policy.host
                and row.get('reason') is None, 'ordinary_entry_check_not_passed')
        require(migration.approved_path(row.get('realpath'), (root,)) is not None,
                'entry_realpath_outside_own_library')
        require(start <= timestamp(row.get('observed_at'), 'entry') <= end, 'entry_time_outside_observation')
        require(mount(row.get('mount')) == checked_mount, 'entry_mount_mismatch')
        item = {key: row[key] for key in OBSERVATION_FIELDS if key in row}
        item['mount'] = checked_mount
        clean.append(item)
    require(seen == required, 'all_destination_entries_required')
    checks = value.get('root_checks')
    require(isinstance(checks, list) and len(checks) == 2, 'current_alias_checks_required')
    aliases = []
    for name, (old, new) in migration.ROOT_PAIRS.items():
        matching = [item for item in checks if isinstance(item, dict) and item.get('path') == old]
        require(len(matching) == 1, 'current_alias_check_missing')
        item = matching[0]
        require(item.get('kind') == 'symlink' and item.get('verified') is True
                and item.get('target') == new and item.get('realpath') == new, 'current_alias_check_failed')
        require(start <= timestamp(item.get('observed_at'), 'alias') <= end, 'alias_time_outside_observation')
        require(inode(item.get('destination_inode')) == binding[name], 'current_root_inode_changed')
        aliases.append({'path': old, 'target': new, 'kind': 'symlink', 'verified': True,
                        'observed_at': item['observed_at'], 'host': policy.host})
    disk = value.get('disk_snapshot')
    require(isinstance(disk, dict) and disk.get('mount') == '/data/share', 'shared_disk_snapshot_required')
    total = integer(disk.get('total_bytes'), 'disk_total', 1)
    available = integer(disk.get('available_bytes'), 'disk_available')
    require(available <= total and start <= timestamp(disk.get('observed_at'), 'disk') <= end,
            'shared_disk_snapshot_invalid')
    return clean, aliases, checked_mount, {key: disk[key] for key in ('mount', 'total_bytes', 'available_bytes', 'observed_at')}


def prepare_bundle(policy=None, host_provider=socket.gethostname):
    policy = policy or Policy()
    require(host_provider() == policy.host, 'publisher_host_mismatch')
    require(policy.project.resolve() == policy.project and policy.base.resolve() == policy.base,
            'configured_root_is_symlink')
    reader = Reader(policy)
    baseline_raw = reader.read(BASELINE_REF, project=True)
    require(sha256(baseline_raw) == policy.baseline_sha256, 'project_baseline_hash_mismatch')
    require(reader.read('catalog-baseline.json') == baseline_raw, 'private_baseline_hash_mismatch')
    baseline = json.loads(baseline_raw)
    assets = baseline.get('assets', [])
    require(len(assets) == policy.record_count and len({row['path'] for row in assets}) == policy.path_count,
            'baseline_record_or_path_count_mismatch')
    registry = reader.document('data/resource-registry.json', project=True)
    previous = reader.document('data/path-migration.json', project=True)
    require(previous.get('migration_id') == MIGRATION_ID and previous.get('baseline_catalog') ==
            {'ref': BASELINE_REF, 'sha256': policy.baseline_sha256}, 'existing_plan_binding_mismatch')
    try:
        migration.validate_manifest(previous, baseline, registry, policy.project)
    except (ValueError, OSError, KeyError):
        raise PublishError('existing_migration_plan_invalid') from None
    actual_digest, _ = reader.digest('source-files.jsonl.gz')
    require(actual_digest == policy.manifest_sha256, 'source_manifest_hash_mismatch')
    transfer = reader.document('transfer-state.json')
    require(transfer.get('migration_id') == MIGRATION_ID and transfer.get('host') == policy.host
            and transfer.get('stage') == policy.stage, 'transfer_identity_mismatch')
    require(transfer.get('phase') == 'verify' and transfer.get('status') == 'passed'
            and set(transfer.get('roots', {})) == set(NAMES), 'checksum_phase_not_passed')
    checked_mount = mount(transfer.get('mount'))
    verification_binding = transfer.get('verification_binding', {})
    require(verification_binding.get('source_manifest_sha256') == actual_digest
            and set(verification_binding.get('staged_roots', {})) == set(NAMES), 'verification_binding_mismatch')
    binding = {name: inode(verification_binding['staged_roots'][name]) for name in NAMES}
    copy_rows, verify_rows = [], []
    for name in NAMES:
        for phase, output in (('copy', copy_rows), ('verification', verify_rows)):
            row = transfer['roots'][name].get(phase, {})
            log_name = name + ('-copy.log' if phase == 'copy' else '-verification.log')
            digest, size = reader.digest(log_name)
            require(row.get('status') == 'passed' and type(row.get('exit_code')) is int and row['exit_code'] == 0
                    and row.get('log') == str(policy.base / log_name) and row.get('log_sha256') == digest,
                    'copy_or_verification_log_binding_failed')
            command = (['rsync', '-aH', '--numeric-ids', '--one-file-system', '--bwlimit=204800', '--stats',
                        '/data/' + name, policy.stage + '/'] if phase == 'copy' else
                       ['rsync', '-aHnc', '--numeric-ids', '--one-file-system', '--delete', '--dry-run',
                        '--itemize-changes', '--out-format=%i %n%L', '/data/' + name + '/', policy.stage + '/' + name + '/'])
            require(row.get('command') == command, 'unexpected_transfer_command')
            require(phase != 'verification' or size == 0, 'checksum_dry_run_has_differences')
            require(timestamp(row.get('started_at'), phase + '_start') <= timestamp(row.get('finished_at'), phase + '_finish'),
                    'transfer_time_order_invalid')
            output.append({'logical_root': name, 'source_root': '/data/' + name,
                           'published_target_root': '/data/share/' + name, 'status': 'passed',
                           'exit_code': 0, 'started_at': row['started_at'], 'finished_at': row['finished_at'],
                           'log_sha256': digest, 'log_bytes': size})
        require(timestamp(copy_rows[-1]['finished_at'], 'copy') <= timestamp(verify_rows[-1]['started_at'], 'verify'),
                'verification_precedes_copy')
    verification_end = max(timestamp(row['finished_at'], 'verify') for row in verify_rows)
    journal = reader.document('cutover-state.json')
    require(journal.get('migration_id') == MIGRATION_ID and journal.get('host') == policy.host
            and journal.get('phase') in ('switched', 'cleaned') and set(journal.get('roots', {})) == set(NAMES),
            'complete_cutover_required')
    switched = timestamp(journal.get('switched_at'), 'switched')
    require(verification_end <= switched, 'cutover_precedes_verification')
    for name in NAMES:
        row = journal['roots'][name]
        require(row.get('publication') == 'published' and row.get('switch') == 'switched'
                and inode(row.get('destination_inode')) == binding[name], 'published_inode_or_switch_mismatch')
        require(verification_end <= timestamp(row.get('published_at'), 'publication')
                <= timestamp(row.get('switched_at'), 'root_switch') <= switched, 'root_switch_time_order_invalid')
    source_before = audit(reader, 'source-before-switch.json', policy, 'source')
    source_after = audit(reader, 'source-after-switch.json', policy, 'rollback')
    usage_before = audit(reader, 'usage-before-switch.json', policy)
    usage_after = audit(reader, 'usage-after-switch.json', policy)
    require(verification_end <= timestamp(source_before['observed_at'], 'source_before')
            <= timestamp(usage_before['observed_at'], 'usage_before') <= switched, 'preflight_time_order_invalid')
    require(max(timestamp(journal['roots'][name]['switched_at'], 'root_switch') for name in NAMES)
            <= timestamp(source_after['observed_at'], 'source_after')
            <= timestamp(usage_after['observed_at'], 'usage_after') <= switched, 'post_switch_audit_time_invalid')
    semantics = reader.document('source-semantics.json', limit=128 * 1024 * 1024)
    require(semantics.get('complete') is True and set(semantics.get('roots', {})) == set(migration.OLD_ROOTS),
            'source_semantics_incomplete')
    for name in NAMES:
        row = semantics['roots']['/data/' + name]
        require(row.get('entries') == policy.root_counts[name] and row.get('xattr_counts') == {},
                'source_semantics_not_bound_or_unsupported_attributes')
    links = reader.document('link-audit.json', limit=512 * 1024 * 1024)
    counts = links.get('counts', {})
    require(links.get('complete') is True and links.get('passed') is True and links.get('errors') == []
            and links.get('source_manifest_sha256') == actual_digest, 'link_relocation_audit_not_passed')
    require(counts.get('manifest_rows') == sum(policy.root_counts.values())
            and all(counts.get(key) == 0 for key in ('errors', 'new_cycles', 'new_depth_limits',
                                                    'relative_relocation_hazards', 'other_relocation_hazards')),
            'link_relocation_audit_counts_invalid')
    link_count_fields = ('symlinks', 'relative_links', 'absolute_internal_alias_dependencies',
                         'absolute_external_node_dependencies', 'preexisting_cycles', 'preexisting_depth_limits')
    link_counts = {key: integer(counts.get(key), 'link_count') for key in link_count_fields}
    require(timestamp(links.get('observed_at'), 'link_audit') <= switched, 'link_audit_after_switch')
    observations_raw = reader.document('destination-entry-observations.json')
    observations, aliases, observed_mount, disk = validate_observations(
        observations_raw, journal, reader.hashes['cutover-state.json'], baseline, policy, binding)
    require(observed_mount == checked_mount, 'transfer_and_current_mount_differ')
    common = {'schema_version': '1.0', 'migration_id': MIGRATION_ID, 'host': policy.host,
              'baseline_catalog_sha256': policy.baseline_sha256, 'source_manifest_sha256': actual_digest}
    reports = {
        'copy': {**common, 'status': 'passed', 'observed_at': max(copy_rows, key=lambda row: timestamp(row['finished_at'], 'copy'))['finished_at'],
                 'strategy': 'rsync archive + hardlinks + numeric ownership; staged directory identities preserved on publication',
                 'roots': copy_rows, 'transfer_state_sha256': reader.hashes['transfer-state.json']},
        'verification': {**common, 'status': 'passed', 'observed_at': observations_raw['observed_at'],
                         'strategy': 'Two empty rsync -aHnc checksum dry runs, source metadata revalidation and all registered destination entries checked as rmp after cutover',
                         'errors': [], 'roots': verify_rows, 'observations': observations,
                         'ordinary_account_checked_paths': len(observations), 'source_after_switch': source_after,
                         'usage_after_switch': usage_after, 'destination_observation_sha256': reader.hashes['destination-entry-observations.json']},
        'cutover': {**common, 'status': 'passed', 'observed_at': journal['switched_at'],
                    'phase': journal['phase'], 'mount': observed_mount, 'disk_snapshot': disk, 'aliases': aliases,
                    'aliases_checked_at': observations_raw['observed_at'], 'cutover_state_sha256': reader.hashes['cutover-state.json']},
        'preflight': {**common, 'status': 'passed', 'observed_at': usage_before['observed_at'],
                      'mount': checked_mount, 'source_before_switch': source_before, 'usage_before_switch': usage_before,
                      'source_semantics': {'complete': True, 'unsupported_xattrs': 0,
                                           'receipt_sha256': reader.hashes['source-semantics.json']},
                      'link_relocation_audit': {'status': 'passed', 'observed_at': links['observed_at'],
                                                'receipt_sha256': reader.hashes['link-audit.json'], 'counts': link_counts,
                                                'scope': 'no_new_relocation_hazards_not_all_links_usable'}},
    }
    if journal['phase'] == 'cleaned':
        started = timestamp(journal.get('cleanup_started_at'), 'cleanup_start')
        cleaned = timestamp(journal.get('cleaned_at'), 'cleanup_finish')
        require(switched <= started <= cleaned, 'cleanup_time_order_invalid')
        before_cleanup = audit(reader, 'source-before-cleanup.json', policy, 'rollback')
        usage_cleanup = audit(reader, 'usage-before-cleanup.json', policy)
        require(switched <= timestamp(before_cleanup['observed_at'], 'source_cleanup')
                <= timestamp(usage_cleanup['observed_at'], 'usage_cleanup') <= started, 'cleanup_preflight_time_invalid')
        deleted = []
        for name in NAMES:
            row = journal['roots'][name]
            require(row.get('cleanup') == 'deleted', 'both_original_trees_must_be_deleted')
            when = timestamp(row.get('deleted_at'), 'root_cleanup')
            usage = audit(reader, 'usage-before-delete-' + name + '.json', policy)
            require(started <= timestamp(usage['observed_at'], 'delete_usage') <= when <= cleaned,
                    'root_cleanup_time_invalid')
            deleted.append({'logical_root': name, 'status': 'deleted', 'deleted_at': row['deleted_at'],
                            'usage_before_delete': usage})
        before = integer(journal.get('local_available_before_cleanup'), 'local_available_before')
        after = integer(journal.get('local_available_after_cleanup'), 'local_available_after')
        reports['cleanup'] = {**common, 'status': 'passed', 'observed_at': journal['cleaned_at'],
                              'started_at': journal['cleanup_started_at'], 'roots': deleted,
                              'source_before_cleanup': before_cleanup, 'usage_before_cleanup': usage_cleanup,
                              'local_space_observation': {'mount': '/data', 'available_before_bytes': before,
                                                         'available_after_bytes': after, 'net_available_change_bytes': after - before,
                                                         'note': 'Observed filesystem free-space difference; concurrent activity may contribute. Not an inferred exact reclaimed-data size.'},
                              'cutover_state_sha256': reader.hashes['cutover-state.json']}
    else:
        reports['cleanup'] = {**common, 'status': 'not_completed', 'observed_at': journal['switched_at'],
                              'note': 'No completed cleanup receipt in the checked transaction journal.'}
    manifest = migration.planned_manifest(baseline, registry, BASELINE_REF, policy.baseline_sha256, MIGRATION_ID)
    manifest['state'] = 'switched'
    files = {}
    for name in REPORT_NAMES:
        payload = json_bytes(reports[name])
        digest = sha256(payload)
        ref = 'data/migration-evidence/objects/' + digest + '.json'
        files[ref] = payload
        files['data/migration-evidence/' + name + '.json'] = payload
        manifest['receipts'][name] = {key: copy.deepcopy(reports[name][key]) for key in
                                      ('status', 'host', 'observed_at', 'strategy', 'errors', 'observations', 'mount', 'disk_snapshot', 'aliases')
                                      if key in reports[name]}
        manifest['receipts'][name]['evidence'] = {'ref': ref, 'sha256': digest}
    files['data/path-migration.json'] = json_bytes(manifest)
    # Exercise the production validator against exactly the bytes to be published.
    with tempfile.TemporaryDirectory(prefix='rdc-public-receipts-') as temporary:
        stage = Path(temporary)
        for ref, payload in files.items():
            target = stage / ref
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        migration.validate_manifest(manifest, baseline, registry, stage)
    reader.stable()
    return {'files': files, 'manifest': manifest, 'reports': reports, 'reader': reader,
            'policy': policy, 'baseline': baseline, 'registry': registry}


def atomic_write(path, data):
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix='.evidence-', suffix='.tmp', dir=path.parent)
        temporary = Path(name)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def publish_bundle(bundle):
    """Only sanitized project artifacts are written; the active manifest is last."""
    project = bundle['policy'].project
    bundle['reader'].stable()
    paths = {ref: guarded_path(project, ref, exists=False) for ref in bundle['files']}
    for ref, path in paths.items():
        require(ref == 'data/path-migration.json' or ref.startswith('data/migration-evidence/'), 'output_not_allowlisted')
        if '/objects/' in ref and path.exists():
            require(path.read_bytes() == bundle['files'][ref], 'immutable_object_already_differs')
    # The only newly-created directories are these two known public evidence dirs.
    for relative in ('data/migration-evidence', 'data/migration-evidence/objects'):
        directory = guarded_path(project, relative, exists=False)
        directory.mkdir(exist_ok=True, mode=0o755)
    for ref, path in paths.items():
        if '/objects/' in ref and not path.exists():
            atomic_write(path, bundle['files'][ref])
    bundle['reader'].stable()
    migration.validate_manifest(bundle['manifest'], bundle['baseline'], bundle['registry'], project)
    for name in REPORT_NAMES:
        ref = 'data/migration-evidence/' + name + '.json'
        guarded_path(project, ref, exists=False)
        atomic_write(paths[ref], bundle['files'][ref])
    bundle['reader'].stable()
    atomic_write(paths['data/path-migration.json'], bundle['files']['data/path-migration.json'])
    return {'migration_id': MIGRATION_ID, 'state': 'switched', 'host': bundle['policy'].host,
            'cleanup': bundle['reports']['cleanup']['status'],
            'observed_paths': len(bundle['manifest']['receipts']['verification']['observations']),
            'manifest_sha256': sha256(bundle['files']['data/path-migration.json'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=('check', 'publish'), default='check')
    args = parser.parse_args()
    try:
        bundle = prepare_bundle()
        if args.action == 'publish':
            result = publish_bundle(bundle)
        else:
            result = {'checked': True, 'written': False, 'migration_id': MIGRATION_ID,
                      'cleanup': bundle['reports']['cleanup']['status'],
                      'observed_paths': len(bundle['manifest']['receipts']['verification']['observations'])}
        print(json.dumps(result))
    except Exception as exc:
        # Private input filenames, process records and link targets never reach stdout.
        print(json.dumps({'checked': False, 'error': str(exc) if isinstance(exc, PublishError) else type(exc).__name__}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
