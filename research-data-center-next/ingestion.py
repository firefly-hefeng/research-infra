"""Rules-only ingestion, with a local coordinator and immutable READY receipts.

No model execution, extraction, network downloads or source deletion. Publication
is an explicit, digest-bound management action into the two managed namespaces.
"""
import dataclasses
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import sqlite3
import stat
import subprocess
import uuid

try:
    import fcntl
    import pwd
except ImportError:  # Read-only snapshot is also usable on Windows.
    fcntl = pwd = None

SCHEMA = '2.0'
DEFAULT_DB = Path('/var/lib/research-data-center/state/ingestion.sqlite3')
KINDS = ('dataset', 'model', 'feature', 'annotation', 'artifact', 'collection')
STATES = ('submitted', 'validating', 'needs_information', 'review_required', 'ready', 'publishing', 'published', 'failed')
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z')
SHA = re.compile(r'[0-9a-f]{64}\Z')
MAX_DOCUMENT = 65536


class IngestionError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise IngestionError(code)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def decode(data):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, 'json_duplicate_key')
            value[key] = item
        return value
    def constant(_):
        raise IngestionError('json_nonfinite_number')
    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def content_digest(submission_hash, manifest_hash):
    return digest((submission_hash + '\n' + manifest_hash).encode('ascii'))


def identifier(value):
    require(isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None, 'invalid_identifier')
    return value


@dataclasses.dataclass(frozen=True)
class Policy:
    state_db: Path = DEFAULT_DB
    incoming: Path = Path('/data/share/incoming')
    datasets: Path = Path('/data/share/datasets/managed')
    models: Path = Path('/data/share/models/managed')
    share: Path = Path('/data/share')
    mount_source: str = '10.0.0.202:/share'
    coordinator_uid: int = 1011
    coordinator_host: str = 'iZuf6jc6bqdgxmhcci4k3wZ'
    max_bytes: int = 10 * 1024 ** 3
    max_files: int = 100000
    max_entries: int = 200000
    max_depth: int = 64
    check_mounts: bool = True

    def limits(self):
        return {key: getattr(self, key) for key in ('max_bytes', 'max_files', 'max_entries', 'max_depth')}


def mount(path):
    result = subprocess.run(['findmnt', '-J', '-T', str(path), '-o', 'TARGET,SOURCE,FSTYPE,FSROOT'],
                            capture_output=True, text=True, check=True, timeout=10)
    rows = json.loads(result.stdout).get('filesystems', [])
    require(len(rows) == 1, 'mount_identity_unavailable')
    return rows[0]


def no_links(path, allow_missing=False):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'absolute_normal_path_required')
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            require(allow_missing, 'required_path_missing')
            continue
        require(not stat.S_ISLNK(info.st_mode), 'symlink_path_rejected')
    return path


def shared_guard(policy, paths):
    if policy.check_mounts:
        no_links(policy.share)
        shared = mount(policy.share)
        require(shared.get('target') == str(policy.share) and shared.get('source') == policy.mount_source
                and shared.get('fstype') in ('nfs', 'nfs3') and shared.get('fsroot') == '/',
                'unexpected_shared_mount')
        device = policy.share.stat().st_dev
    for path in paths:
        path = no_links(path)
        if policy.check_mounts:
            require(path.is_relative_to(policy.share), 'unexpected_shared_mount')
            info = mount(path)
            if info != shared:
                # systemd ReadWritePaths exposes these exact managed directories
                # as NFS mounts in the service namespace. On the verified host,
                # findmnt expands SOURCE to the export subpath; FSROOT stays /.
                # No arbitrary nested mount, incoming bind, or alternate source
                # spelling is accepted by this narrowly scoped exception.
                matches = [prefix for prefix in (policy.datasets, policy.models)
                           if prefix.is_relative_to(policy.share) and prefix != policy.share
                           and path.is_relative_to(prefix) and info.get('target') == str(prefix)]
                require(len(matches) == 1, 'unexpected_shared_mount')
                prefix = matches[0]
                expected_source = policy.mount_source + '/' + prefix.relative_to(policy.share).as_posix()
                require(info.get('source') == expected_source and info.get('fstype') == shared['fstype']
                        and info.get('fsroot') == '/' and mount(prefix.parent) == shared,
                        'unexpected_shared_mount')
                require(prefix.stat().st_dev == device and prefix.parent.stat().st_dev == device,
                        'unexpected_shared_mount_device')
            require(path.stat().st_dev == device, 'unexpected_shared_mount_device')
    if policy.check_mounts:
        require(mount(policy.share) == shared and policy.share.stat().st_dev == device,
                'shared_mount_changed_during_guard')


def text(value, code, limit=8000):
    require(isinstance(value, str) and value.strip() and len(value) <= limit
            and not any(ord(c) < 32 and c not in '\n\t' for c in value), code)


def validate_submission(value):
    require(isinstance(value, dict), 'submission_must_be_object')
    required = {'schema_version', 'type', 'title', 'summary', 'source', 'rights', 'contributor'}
    require(set(value) == required and value['schema_version'] == SCHEMA, 'submission_schema_invalid')
    require(value['type'] in KINDS, 'submission_type_invalid')
    text(value['title'], 'title_required', 300)
    text(value['summary'], 'summary_required')
    definitions = {'source': ({'description'}, {'description', 'reference'}),
                   'rights': ({'team_use', 'external_distribution'}, {'team_use', 'external_distribution', 'basis', 'license_id'}),
                   'contributor': ({'name'}, {'name', 'contact'})}
    for key, (needed, allowed) in definitions.items():
        item = value[key]
        require(isinstance(item, dict) and needed <= set(item) <= allowed, key + '_fields_invalid')
        for field, val in item.items():
            if field not in needed and val is None:
                continue
            text(val, key + '_' + field + '_invalid')
    require(value['rights']['team_use'] in ('allowed', 'restricted', 'unknown'), 'team_use_invalid')
    require(value['rights']['external_distribution'] in ('allowed', 'conditional', 'prohibited', 'unknown'),
            'external_distribution_invalid')
    return value


def submission_location(directory, policy):
    directory = no_links(Path(directory).absolute())
    try:
        parts = directory.relative_to(policy.incoming).parts
    except ValueError:
        raise IngestionError('submission_outside_incoming') from None
    require(len(parts) == 2, 'submission_location_requires_user_and_id')
    user, sid = map(identifier, parts)
    shared_guard(policy, [policy.incoming, directory])
    return directory, user, sid


def read_regular(path, limit=MAX_DOCUMENT):
    no_links(path)
    fd = open_absolute(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= limit, 'unsafe_metadata_file')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(limit + 1)
        require(len(data) <= limit, 'metadata_size_limit')
        require(signature(os.fstat(fd)) == signature(info), 'metadata_changed_while_reading')
        return data
    finally:
        os.close(fd)


def signature(info):
    return tuple(getattr(info, 'st_' + key) for key in ('dev', 'ino', 'mode', 'size', 'mtime_ns', 'ctime_ns', 'nlink'))


def open_absolute(path, flags):
    """Open without following symlinks in *any* component, including racing parents."""
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'absolute_normal_path_required')
    parent = os.open('/', os.O_PATH | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent); parent = child
        return os.open(path.name or '.', flags | os.O_NOFOLLOW, dir_fd=parent)
    finally:
        os.close(parent)


def valid_relative(value):
    require(isinstance(value, str) and value and '\\' not in value
            and not any(ord(c) < 32 for c in value), 'manifest_path_invalid')
    parsed = PurePosixPath(value)
    require(not parsed.is_absolute() and '..' not in parsed.parts and str(parsed) == value
            and all(part not in ('', '.', '..') for part in parsed.parts), 'manifest_path_invalid')
    return parsed.parts


def hash_file(fd, expected, sink=None):
    require(stat.S_ISREG(expected.st_mode) and expected.st_nlink == 1, 'payload_not_independent_regular_file')
    hasher, size = hashlib.sha256(), 0
    while True:
        block = os.read(fd, 1024 * 1024)
        if not block:
            break
        size += len(block)
        require(size <= expected.st_size, 'payload_grew_during_read')
        hasher.update(block)
        if sink:
            sink.write(block)
    require(size == expected.st_size and signature(os.fstat(fd)) == signature(expected), 'payload_changed_during_read')
    return hasher.hexdigest()


def payload_manifest(payload, policy):
    """Anchored directory walk: no symlinks, special files, external hardlinks or mounts."""
    no_links(payload)
    root_fd = open_absolute(payload, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_device = os.fstat(root_fd).st_dev
    entries, files, total = [], 0, 0
    def walk(parent, prefix, depth):
        nonlocal files, total
        require(depth <= policy.max_depth, 'manual_review_depth_limit')
        before = os.fstat(parent)
        with os.scandir(parent) as iterator:
            names = []
            for item in iterator:
                names.append(item.name)
                require(len(names) + len(entries) <= policy.max_entries, 'manual_review_entry_limit')
        for name in sorted(names):
            relative = '/'.join(prefix + [name])
            valid_relative(relative)
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            require(info.st_dev == root_device, 'nested_mount_rejected')
            require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode), 'links_or_special_files_rejected')
            require(len(entries) < policy.max_entries, 'manual_review_entry_limit')
            if stat.S_ISDIR(info.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                try:
                    require(signature(os.fstat(child)) == signature(info), 'payload_directory_changed')
                    entries.append({'path': relative, 'kind': 'directory', 'size_bytes': 0, 'sha256': None})
                    walk(child, prefix + [name], depth + 1)
                finally:
                    os.close(child)
            else:
                files += 1
                total += info.st_size
                require(files <= policy.max_files and total <= policy.max_bytes, 'manual_review_size_or_file_limit')
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                try:
                    require(signature(os.fstat(fd)) == signature(info), 'payload_file_changed')
                    sha = hash_file(fd, info)
                finally:
                    os.close(fd)
                entries.append({'path': relative, 'kind': 'file', 'size_bytes': info.st_size, 'sha256': sha})
        after = os.fstat(parent)
        require((before.st_ino, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_ino, after.st_mtime_ns, after.st_ctime_ns), 'payload_directory_changed')
    try:
        walk(root_fd, [], 0)
    finally:
        os.close(root_fd)
    return sorted(entries, key=lambda row: row['path']), files, total


def create_once(path, data, mode=0o644):
    """Exclusive final creation: on failure no partial file is called READY."""
    path = Path(path)
    parent = open_absolute(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = '.incoming-' + uuid.uuid4().hex
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=parent)
        try:
            os.fchmod(fd, mode)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # link is atomic and refuses an existing destination, including symlinks.
            os.link(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        finally:
            os.unlink(temporary, dir_fd=parent)
        os.fsync(parent)
    finally:
        os.close(parent)


def sync_dir(path):
    fd = open_absolute(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def prepare(directory, policy=None):
    policy = policy or Policy()
    require(pwd is not None and os.getuid() != 0 and os.getuid() == os.geteuid(), 'ordinary_account_required')
    directory, user, sid = submission_location(directory, policy)
    require(pwd.getpwuid(os.getuid()).pw_name == user, 'submission_must_belong_to_current_user')
    require(directory.stat().st_uid == os.getuid(), 'submission_directory_owner_mismatch')
    require(not os.path.lexists(directory / 'READY.json') and not os.path.lexists(directory / 'manifest.jsonl'),
            'existing_submission_not_overwritten')
    raw = read_regular(directory / 'submission.json')
    validate_submission(decode(raw))
    shared_guard(policy, [directory / 'payload'])
    rows, files, total = payload_manifest(directory / 'payload', policy)
    manifest = b''.join(encode(row) for row in rows)
    sh, mh = digest(raw), digest(manifest)
    receipt = {'schema_version': SCHEMA, 'submission_id': sid, 'user': user, 'submission_sha256': sh,
               'manifest_sha256': mh, 'content_digest': content_digest(sh, mh), 'submitted_at': now(),
               'file_count': files, 'entry_count': len(rows), 'total_bytes': total}
    # Recheck metadata identity before committing the readiness marker.
    require(read_regular(directory / 'submission.json') == raw, 'submission_changed_before_ready')
    create_once(directory / 'manifest.jsonl', manifest, 0o640)
    create_once(directory / 'READY.json', encode(receipt), 0o640)
    return {'submission_id': sid, 'user': user, 'status': 'submitted', **receipt}


def read_submission(directory, policy, verify=False):
    directory, user, sid = submission_location(directory, policy)
    bucket_uid = directory.parent.stat().st_uid
    source_uid = directory.stat().st_uid
    require(source_uid == bucket_uid, 'submission_owner_disagrees_with_bucket')
    ready = decode(read_regular(directory / 'READY.json'))
    require(isinstance(ready, dict) and ready.get('schema_version') == SCHEMA
            and ready.get('submission_id') == sid and ready.get('user') == user, 'ready_identity_mismatch')
    require(set(ready) == {'schema_version', 'submission_id', 'user', 'submission_sha256', 'manifest_sha256',
                           'content_digest', 'submitted_at', 'file_count', 'entry_count', 'total_bytes'}, 'ready_fields_invalid')
    for key in ('file_count', 'entry_count', 'total_bytes'):
        require(type(ready.get(key)) is int and ready[key] >= 0, 'ready_counts_invalid')
    require(ready['file_count'] <= policy.max_files and ready['entry_count'] <= policy.max_entries
            and ready['total_bytes'] <= policy.max_bytes, 'manual_review_size_or_file_limit')
    try:
        require(isinstance(ready.get('submitted_at'), str), 'ready_timestamp_invalid')
        stamp = dt.datetime.fromisoformat(ready['submitted_at'].replace('Z', '+00:00'))
        require(stamp.tzinfo is not None, 'ready_timestamp_invalid')
    except (KeyError, TypeError, ValueError):
        raise IngestionError('ready_timestamp_invalid') from None
    raw = read_regular(directory / 'submission.json')
    document = validate_submission(decode(raw))
    manifest = read_regular(directory / 'manifest.jsonl', max(MAX_DOCUMENT, policy.max_entries * 512))
    sh, mh = digest(raw), digest(manifest)
    require(ready.get('submission_sha256') == sh and ready.get('manifest_sha256') == mh
            and ready.get('content_digest') == content_digest(sh, mh), 'ready_digest_mismatch')
    rows, seen, total, files = [], set(), 0, 0
    for line in manifest.splitlines():
        row = decode(line)
        require(isinstance(row, dict) and set(row) == {'path', 'kind', 'size_bytes', 'sha256'}, 'manifest_entry_invalid')
        parts = valid_relative(row['path'])
        require(len(parts) <= policy.max_depth + 1 and row['path'] not in seen, 'manifest_duplicate_or_depth_limit')
        seen.add(row['path'])
        require(type(row['size_bytes']) is int and row['size_bytes'] >= 0, 'manifest_size_invalid')
        if row['kind'] == 'file':
            require(isinstance(row['sha256'], str) and SHA.fullmatch(row['sha256']), 'manifest_hash_invalid')
            total += row['size_bytes']; files += 1
        else:
            require(row['kind'] == 'directory' and row['size_bytes'] == 0 and row['sha256'] is None, 'manifest_kind_invalid')
        rows.append(row)
    require(len(rows) == ready['entry_count'] and files == ready['file_count'] and total == ready['total_bytes'], 'manifest_counts_mismatch')
    require(rows == sorted(rows, key=lambda row: row['path']), 'manifest_order_invalid')
    if verify:
        shared_guard(policy, [directory / 'payload'])
        actual, actual_files, actual_bytes = payload_manifest(directory / 'payload', policy)
        require(actual == rows and files == actual_files and total == actual_bytes, 'payload_manifest_mismatch')
    return {'ready': ready, 'submission': document, 'rows': rows, 'submission_bytes': raw, 'manifest_bytes': manifest,
            'identity': {'bucket_uid': bucket_uid, 'source_directory_uid': source_uid,
                         'contributor_name_is_self_reported': True}}


def client_status(directory, policy=None):
    policy = policy or Policy()
    path, user, sid = submission_location(directory, policy)
    if not os.path.lexists(path / 'READY.json'):
        return {'submission_id': sid, 'user': user, 'status': 'preparing', 'ready': False}
    value = read_submission(path, policy)
    return {'submission_id': sid, 'user': user, 'status': 'submitted', 'ready': True,
            **value['ready'], 'note': 'READY is a submission receipt, not acceptance or publication.'}


DB_SCHEMA = '''
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,user TEXT NOT NULL,submission_id TEXT NOT NULL,
 status TEXT NOT NULL,submitted_at TEXT,updated_at TEXT NOT NULL,reason_code TEXT,
 content_digest TEXT,document TEXT,ready TEXT,plan TEXT,approval TEXT,publication TEXT,source_identity TEXT);
CREATE TABLE IF NOT EXISTS events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT,
 at TEXT NOT NULL,event TEXT NOT NULL,details TEXT NOT NULL);
'''


def coordinator_guard(db, policy):
    require(fcntl is not None and pwd is not None and os.getuid() == os.geteuid() == policy.coordinator_uid
            and os.getuid() != 0, 'ordinary_single_coordinator_uid_required')
    require(socket.gethostname() == policy.coordinator_host, 'coordinator_host_not_authorized')
    require(db == policy.state_db.absolute(), 'state_database_not_authorized_by_policy')
    no_links(db, allow_missing=True)
    parent = db.parent
    ancestor = parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    if policy.check_mounts:
        info = mount(ancestor)
        require(info.get('fstype') in ('xfs', 'ext4', 'ext3', 'btrfs', 'zfs'), 'state_must_be_local_persistent_filesystem')
    require(not any(db.is_relative_to(root) for root in (policy.share, policy.incoming, policy.datasets, policy.models)),
            'state_database_must_be_outside_shared_storage')
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(parent.stat().st_uid == os.getuid() and stat.S_IMODE(parent.stat().st_mode) & 0o077 == 0,
            'state_directory_must_be_private_and_owned')
    for suffix in ('', '-wal', '-shm', '.lock'):
        path = Path(str(db) + suffix)
        if os.path.lexists(path):
            no_links(path)
            require(path.stat().st_uid == os.getuid() and stat.S_ISREG(path.stat().st_mode), 'state_file_owner_or_type_invalid')


class Coordinator:
    def __init__(self, state_db=DEFAULT_DB, policy=None):
        self.db_path = Path(state_db).absolute()
        self.policy = policy or Policy()
        self.connection = None

    def __enter__(self):
        coordinator_guard(self.db_path, self.policy)
        self.lock_fd = os.open(str(self.db_path) + '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(self.lock_fd)
            raise IngestionError('coordinator_already_running') from None
        try:
            self.connection = sqlite3.connect(self.db_path)
            self.connection.row_factory = sqlite3.Row
            os.chmod(self.db_path, 0o600)
            self.connection.executescript(DB_SCHEMA)
            self.connection.execute('PRAGMA journal_mode=DELETE')
            self.connection.execute('PRAGMA synchronous=FULL')
            host = socket.gethostname()
            previous = self.meta('coordinator_host')
            require(previous in (None, host), 'state_database_bound_to_another_host')
            self.set_meta('coordinator_host', host)
            self.set_meta('limits', self.policy.limits())
            if self.meta('worker_enabled') is None:
                self.set_meta('worker_enabled', True)
            self.connection.commit()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        if self.connection is not None:
            self.connection.close()
        os.close(self.lock_fd)

    def meta(self, key):
        row = self.connection.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_meta(self, key, value):
        self.connection.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, json.dumps(value)))

    def heartbeat(self):
        require(self.meta('worker_enabled') is not False, 'worker_disabled')
        self.set_meta('last_heartbeat_at', now())
        self.connection.commit()

    def job(self, job_id):
        row = self.connection.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        require(row is not None, 'unknown_job')
        return dict(row)

    def event(self, job_id, event, details=None):
        self.connection.execute('INSERT INTO events(job_id,at,event,details) VALUES (?,?,?,?)',
                                (job_id, now(), event, json.dumps(details or {}, ensure_ascii=False)))

    def change(self, job_id, status, reason=None, **fields):
        require(status in STATES and set(fields) <= {'document', 'ready', 'plan', 'approval', 'publication', 'content_digest', 'source_identity'},
                'invalid_internal_state_change')
        values = {'status': status, 'updated_at': now(), 'reason_code': reason, **fields}
        self.connection.execute('UPDATE jobs SET ' + ','.join(key + '=?' for key in values) + ' WHERE id=?',
                                [json.dumps(val, ensure_ascii=False) if isinstance(val, dict) else val for val in values.values()] + [job_id])
        self.event(job_id, status, {'reason_code': reason})
        self.connection.commit()
        return self.job(job_id)

    def source(self, job):
        return self.policy.incoming / identifier(job['user']) / identifier(job['submission_id'])

    def scan(self):
        self.heartbeat()
        shared_guard(self.policy, [self.policy.incoming])
        found, visited = [], 0
        with os.scandir(self.policy.incoming) as users:
            for account in users:
                visited += 1
                require(visited <= 10000, 'scan_submission_limit')
                if not IDENTIFIER.fullmatch(account.name) or not account.is_dir(follow_symlinks=False):
                    continue
                with os.scandir(account.path) as submissions:
                    for entry in submissions:
                        visited += 1
                        require(visited <= 10000, 'scan_submission_limit')
                        if not IDENTIFIER.fullmatch(entry.name) or not entry.is_dir(follow_symlinks=False):
                            continue
                        directory = Path(entry.path)
                        if not os.path.lexists(directory / 'READY.json'):
                            continue
                        job_id = account.name + '/' + entry.name
                        if self.connection.execute('SELECT 1 FROM jobs WHERE id=?', (job_id,)).fetchone():
                            continue
                        self.connection.execute('INSERT INTO jobs(id,user,submission_id,status,updated_at) VALUES (?,?,?,?,?)',
                                                (job_id, account.name, entry.name, 'submitted', now()))
                        self.event(job_id, 'submitted')
                        self.connection.commit()
                        try:
                            value = read_submission(directory, self.policy)
                            self.connection.execute('UPDATE jobs SET submitted_at=? WHERE id=?', (value['ready']['submitted_at'], job_id))
                            self.change(job_id, 'submitted', document=value['submission'], ready=value['ready'],
                                        content_digest=value['ready']['content_digest'], source_identity=value['identity'])
                        except (IngestionError, OSError, ValueError) as exc:
                            code = str(exc) if isinstance(exc, IngestionError) else type(exc).__name__
                            state = 'review_required' if code.startswith('manual_review_') else 'failed'
                            self.change(job_id, state, code)
                        found.append(job_id)
        return found

    def verify(self, job_id):
        self.heartbeat()
        job = self.job(job_id)
        require(job['status'] not in ('published', 'publishing'), 'published_or_in_progress_job_is_immutable')
        self.change(job_id, 'validating', approval=None, plan=None)
        try:
            value = read_submission(self.source(job), self.policy, verify=True)
            require(not job['content_digest'] or job['content_digest'] == value['ready']['content_digest'], 'submission_identity_changed_resubmit_required')
            rights = value['submission']['rights']['team_use']
            state, reason = ('needs_information', 'team_use_permission_unknown') if rights == 'unknown' else ('review_required', 'management_target_approval_required')
            if rights == 'restricted':
                reason = 'team_use_restriction_requires_resolution'
            return self.change(job_id, state, reason, document=value['submission'], ready=value['ready'],
                               content_digest=value['ready']['content_digest'], source_identity=value['identity'])
        except (IngestionError, OSError, ValueError) as exc:
            code = str(exc) if isinstance(exc, IngestionError) else type(exc).__name__
            return self.change(job_id, 'review_required' if code.startswith('manual_review_') else 'failed', code)

    def target(self, kind, resource_id, version):
        require(kind in ('dataset', 'model'), 'managed_kind_must_be_dataset_or_model')
        return (self.policy.models if kind == 'model' else self.policy.datasets) / identifier(resource_id) / identifier(version)

    def plan(self, job_id, kind, resource_id, version):
        job = self.verify(job_id)
        require(job['status'] == 'review_required' and job['reason_code'] == 'management_target_approval_required', 'submission_not_eligible_for_plan')
        target = self.target(kind, resource_id, version)
        document = json.loads(job['document'])
        require((document['type'] == 'model') == (kind == 'model'), 'target_kind_disagrees_with_submission')
        plan = {'schema_version': '1.0', 'job_id': job_id, 'content_digest': job['content_digest'], 'kind': kind,
                'resource_id': resource_id, 'version': version, 'target_path': str(target), 'planned_at': now(),
                'actions': ['copy_independent_files', 'verify_sha256', 'write_READY_last'],
                'source_retained': True, 'existing_libraries_modified': False, 'curation_status': 'team_card_pending'}
        return self.change(job_id, 'review_required', 'management_target_approval_required', plan=plan)

    def approve(self, job_id, expected_digest, kind, resource_id, version):
        require(isinstance(expected_digest, str) and SHA.fullmatch(expected_digest), 'approval_digest_required')
        job = self.plan(job_id, kind, resource_id, version)
        require(job['content_digest'] == expected_digest, 'approval_digest_mismatch')
        target = self.target(kind, resource_id, version)
        require(not os.path.lexists(target), 'publication_target_already_exists')
        conflicts = self.connection.execute("SELECT id,plan FROM jobs WHERE id!=? AND status IN ('ready','publishing','published')", (job_id,)).fetchall()
        require(not any(row['plan'] and json.loads(row['plan']).get('target_path') == str(target) for row in conflicts), 'target_reserved_by_other_job')
        approval = {'content_digest': expected_digest, 'kind': kind, 'resource_id': resource_id, 'version': version,
                    'target_path': str(target), 'approved_at': now(), 'actor': pwd.getpwuid(os.getuid()).pw_name,
                    'authority': 'local_coordinator_cli', 'policy': 'exact_digest_resource_version',
                    'rights_decision': 'management_authorized_team_use',
                    'submitted_rights': json.loads(job['document'])['rights'],
                    'external_distribution_granted': False}
        self.event(job_id, 'approval', approval)
        return self.change(job_id, 'ready', approval=approval)

    def publish(self, job_id):
        self.heartbeat()
        job = self.job(job_id)
        require(job['status'] in ('ready', 'publishing', 'published') and job['approval'], 'publication_requires_digest_bound_approval')
        plan, approval = json.loads(job['plan']), json.loads(job['approval'])
        require(all(plan.get(key) == approval.get(key) for key in ('content_digest', 'kind', 'resource_id', 'version', 'target_path')),
                'approval_plan_mismatch')
        target = self.target(plan['kind'], plan['resource_id'], plan['version'])
        require(str(target) == plan['target_path'], 'policy_target_changed')
        managed = self.policy.models if plan['kind'] == 'model' else self.policy.datasets
        shared_guard(self.policy, [managed])
        managed_info = managed.stat()
        require(managed_info.st_uid == self.policy.coordinator_uid and stat.S_IMODE(managed_info.st_mode) & 0o022 == 0,
                'managed_namespace_must_have_single_writer')
        if job['status'] in ('publishing', 'published'):
            return self.reconcile(job, target)
        try:
            value = read_submission(self.source(job), self.policy, verify=True)
            require(value['ready']['content_digest'] == approval['content_digest'], 'approved_content_changed')
            require(value['identity'] == json.loads(job['source_identity']), 'approved_source_owner_changed')
        except (IngestionError, OSError, ValueError):
            self.change(job_id, 'failed', 'approved_content_or_identity_changed', approval=None)
            raise
        self.change(job_id, 'publishing')
        try:
            no_links(target.parent, allow_missing=True)
            target.parent.mkdir(mode=0o755, exist_ok=True)
            target.mkdir(mode=0o755)  # Exclusive reservation; never overwrite another version.
            create_once(target / '.INGEST.json', encode({'job_id': job_id, 'content_digest': approval['content_digest']}))
            (target / 'payload').mkdir(mode=0o755)
            self.copy_payload(self.source(job) / 'payload', target / 'payload', value['rows'])
            # Compare the source once more: READY does not freeze open writers.
            current = read_submission(self.source(job), self.policy, verify=True)
            require(current['ready'] == value['ready'], 'source_changed_during_publication')
            create_once(target / 'submission.json', value['submission_bytes'])
            create_once(target / 'manifest.jsonl', value['manifest_bytes'])
            receipt = {'schema_version': SCHEMA, 'job_id': job_id, 'resource_id': plan['resource_id'],
                       'version': plan['version'], 'kind': plan['kind'], 'target_path': str(target),
                       'content_digest': approval['content_digest'], 'submission_sha256': value['ready']['submission_sha256'],
                       'manifest_sha256': value['ready']['manifest_sha256'], 'file_count': value['ready']['file_count'],
                       'entry_count': value['ready']['entry_count'], 'total_bytes': value['ready']['total_bytes'],
                       'published_at': now(), 'approval': approval, 'source_retained': True}
            create_once(target / 'READY.json', encode(receipt))
            sync_dir(target.parent)
            sync_dir(managed)
            return self.finalize(job, value['submission'], receipt)
        except BaseException:
            # Deliberately remain publishing. Recovery inspects actual READY;
            # incomplete destinations are retained and never silently reused.
            self.event(job_id, 'publication_interrupted', {'target_path': str(target)})
            self.connection.commit()
            raise

    def copy_payload(self, source, destination, rows):
        for row in rows:
            parts = valid_relative(row['path'])
            target = destination.joinpath(*parts)
            no_links(target.parent)
            if row['kind'] == 'directory':
                target.mkdir(mode=0o755)
                continue
            # Open every source component relative to an anchored descriptor.
            parent = open_absolute(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                for name in parts[:-1]:
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                    os.close(parent); parent = child
                fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                try:
                    info = os.fstat(fd)
                    require(info.st_size == row['size_bytes'], 'copy_source_size_changed')
                    out = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
                    with os.fdopen(out, 'wb') as sink:
                        copied_hash = hash_file(fd, info, sink)
                        sink.flush(); os.fsync(sink.fileno())
                    require(copied_hash == row['sha256'], 'copy_source_digest_changed')
                finally:
                    os.close(fd)
            finally:
                os.close(parent)
        actual, _, _ = payload_manifest(destination, self.policy)
        require(actual == rows, 'destination_checksum_mismatch')
        for row in sorted((row for row in rows if row['kind'] == 'directory'),
                          key=lambda row: len(PurePosixPath(row['path']).parts), reverse=True):
            sync_dir(destination.joinpath(*PurePosixPath(row['path']).parts))
        sync_dir(destination)

    def reconcile(self, job, target):
        if not os.path.lexists(target / 'READY.json'):
            self.event(job['id'], 'incomplete_publication_retained', {'target_path': str(target)})
            return self.change(job['id'], 'review_required', 'incomplete_publication_requires_new_version', approval=None)
        receipt = decode(read_regular(target / 'READY.json'))
        approval = json.loads(job['approval'])
        require(receipt.get('job_id') == job['id'] and receipt.get('approval') == approval
                and receipt.get('content_digest') == job['content_digest'] and receipt.get('target_path') == str(target),
                'existing_publication_receipt_mismatch')
        raw = read_regular(target / 'submission.json')
        manifest = read_regular(target / 'manifest.jsonl', max(MAX_DOCUMENT, self.policy.max_entries * 512))
        require(digest(raw) == receipt['submission_sha256'] and digest(manifest) == receipt['manifest_sha256']
                and content_digest(digest(raw), digest(manifest)) == job['content_digest'], 'published_metadata_changed')
        actual, files, total = payload_manifest(target / 'payload', self.policy)
        require(b''.join(encode(row) for row in actual) == manifest and files == receipt['file_count']
                and total == receipt['total_bytes'], 'published_payload_changed')
        if job['status'] == 'published':
            return job
        return self.finalize(job, validate_submission(decode(raw)), receipt)

    def finalize(self, job, document, receipt):
        record = {**receipt, 'title': document['title'], 'summary': document['summary'],
                  'submission_type': document['type'],
                  'source': document['source'], 'rights': document['rights'],
                  'source_identity': json.loads(job['source_identity']) if job.get('source_identity') else {},
                  'maintainer_authority': receipt['approval'], 'curation_status': 'team_card_pending'}
        self.event(job['id'], 'publication_receipt', record)
        return self.change(job['id'], 'published', publication=record)


def readonly_db(state_db):
    path = Path(state_db).absolute()
    if not path.exists():
        return None
    no_links(path)
    require(path.is_file(), 'state_database_not_regular_file')
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    return connection


def snapshot(state_db, *, limit=100):
    require(type(limit) is int and 1 <= limit <= 500, 'snapshot_limit_invalid')
    output = {'schema_version': '1.0', 'mode': 'not-configured', 'observed_at': now(),
              'worker': {'last_heartbeat_at': None, 'stale_after_seconds': 900, 'kind': 'rules', 'llm_enabled': False},
              'counts': {state: 0 for state in STATES}, 'jobs': [], 'limits': Policy().limits(),
              'notes': ['READY means submitted, not published.', 'No model service or GPU work.',
                        'Only digest-bound management authorization can publish.']}
    connection = readonly_db(state_db)
    if connection is None:
        return output
    try:
        meta = {row['key']: json.loads(row['value']) for row in connection.execute('SELECT * FROM meta')}
        heartbeat = meta.get('last_heartbeat_at')
        output['worker']['last_heartbeat_at'] = heartbeat
        output['limits'] = meta.get('limits', output['limits'])
        if meta.get('worker_enabled') is False:
            output['mode'] = 'disabled'
        elif not heartbeat:
            output['mode'] = 'planned'
        else:
            age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(heartbeat)).total_seconds()
            output['mode'] = 'active' if 0 <= age <= 900 else 'worker-stale'
        for row in connection.execute('SELECT status,count(*) AS n FROM jobs GROUP BY status'):
            if row['status'] in STATES:
                output['counts'][row['status']] = row['n']
        for row in connection.execute('SELECT * FROM jobs ORDER BY updated_at DESC,id LIMIT ?', (limit,)):
            document, ready, plan = (json.loads(row[key]) if row[key] else {} for key in ('document', 'ready', 'plan'))
            output['jobs'].append({'id': row['id'], 'user': row['user'], 'status': row['status'],
                                   'submitted_at': row['submitted_at'], 'updated_at': row['updated_at'],
                                   'display_name': document.get('title'), 'kind': document.get('type'),
                                   'reason_code': row['reason_code'], 'content_digest': row['content_digest'],
                                   'file_count': ready.get('file_count'), 'total_bytes': ready.get('total_bytes'),
                                   'target': plan.get('target_path'), 'version': plan.get('version')})
        return output
    finally:
        connection.close()


def published_assets(state_db, *, limit=None):
    require(limit is None or type(limit) is int and 1 <= limit <= 500, 'published_limit_invalid')
    connection = readonly_db(state_db)
    if connection is None:
        return []
    try:
        sql = "SELECT publication FROM jobs WHERE status='published' AND publication IS NOT NULL ORDER BY json_extract(publication,'$.published_at') DESC,id"
        return [json.loads(row[0]) for row in connection.execute(sql + (' LIMIT ?' if limit is not None else ''),
                                                               (limit,) if limit is not None else ())]
    finally:
        connection.close()
