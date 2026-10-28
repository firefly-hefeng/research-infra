"""Bounded, metadata-only collection. Never opens dataset records or model weights."""
import argparse
import collections
import datetime as dt
import json
import itertools
import os
import pathlib
import pwd
import subprocess
import stat
import time
try:
    from tools.path_migration import ROOT_PAIRS, approved_path, destination_path, validate_mount
except ModuleNotFoundError:
    # The collector can also run from a copied tools/ directory on the server.
    from path_migration import ROOT_PAIRS, approved_path, destination_path, validate_mount

IGNORE = {'.git', 'node_modules', '__pycache__', '._____temp', '.locks', 'blobs', '.no_exist', 'optimizer', 'wandb'}
WEIGHTS = {'.safetensors', '.bin', '.pt', '.pth', '.onnx', '.gguf', '.ckpt'}
PUBLIC_ROOTS = [pathlib.Path('/data/datasets'), pathlib.Path('/data/models')]

def in_scope(path):
    if '..' in pathlib.PurePosixPath(str(path)).parts or '\\' in str(path):
        return False
    candidate = pathlib.Path(os.path.abspath(path))
    return any(candidate.is_relative_to(root) for root in PUBLIC_ROOTS)

def safe_path(path):
    return in_scope(path) and in_scope(os.path.realpath(path))

def read_config(path, allowed_roots):
    resolved = path.resolve(strict=True)
    if not any(resolved.is_relative_to(root) for root in allowed_roots):
        raise ValueError('configuration_outside_approved_model_roots')
    fd = os.open(str(resolved), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        # Verify the opened inode as well, before reading any content.
        actual = pathlib.Path(os.path.realpath('/proc/self/fd/' + str(fd)))
        info = os.fstat(fd)
        if not any(actual.is_relative_to(root) for root in allowed_roots):
            raise ValueError('configuration_target_changed')
        if not stat.S_ISREG(info.st_mode) or info.st_size > 200000:
            raise ValueError('configuration_type_or_size_rejected')
        data = os.read(fd, 200001)
        if len(data) > 200000:
            raise ValueError('configuration_size_changed')
        parsed = json.loads(data)
        if not isinstance(parsed, dict):
            raise ValueError('configuration_not_object')
        return parsed
    finally:
        os.close(fd)

def check(path):
    if not safe_path(path):
        return {'exists': None, 'reason': 'outside_public_roots', 'rmp_readable': False}
    try:
        s = os.stat(path)
        try:
            owner = pwd.getpwuid(s.st_uid).pw_name
        except KeyError:
            owner = str(s.st_uid)
        return {'exists': True, 'kind': 'directory' if os.path.isdir(path) else 'file',
                'owner': owner, 'uid': s.st_uid, 'gid': s.st_gid, 'mode': oct(stat.S_IMODE(s.st_mode)),
                'realpath': os.path.realpath(path), 'mtime_ns': s.st_mtime_ns,
                'readable': os.access(path, os.R_OK | (os.X_OK if os.path.isdir(path) else 0))}
    except FileNotFoundError:
        return {'exists': False, 'reason': 'not_found'}
    except PermissionError:
        return {'exists': None, 'reason': 'permission_denied'}
    except OSError as e:
        return {'exists': None, 'reason': type(e).__name__}

def mount_info(path):
    result = subprocess.run(['findmnt', '--json', '--target', str(path), '--output', 'TARGET,SOURCE,FSTYPE'],
                            capture_output=True, text=True, check=True, timeout=10)
    rows = json.loads(result.stdout).get('filesystems', [])
    if len(rows) != 1:
        raise ValueError('mount_identity_unavailable')
    return {key: rows[0][key] for key in ('target', 'source', 'fstype')}


def collect(config):
    """Default stays legacy; shared mode accepts canonical target paths only.

    Destination output cannot itself activate catalog paths. The catalog builder
    still requires a switched manifest and all hashed migration receipts.
    """
    global PUBLIC_ROOTS
    mode = config.get('location_mode', 'legacy')
    if mode not in ('legacy', 'destination_verification', 'shared'):
        raise ValueError('invalid_collection_location_mode')
    old_roots = PUBLIC_ROOTS
    prepared = dict(config)
    try:
        if mode in ('destination_verification', 'shared'):
            new_roots = tuple(pair[1] for pair in ROOT_PAIRS.values())
            if mode == 'shared':
                # Shared configuration is already canonical. Never reinterpret
                # an old alias, relative path, or another share/ subtree.
                if (not isinstance(config.get('paths'), list) or not isinstance(config.get('model_roots'), list)
                        or any(not isinstance(path, str) or approved_path(path, new_roots) != path for path in config['paths'])
                        or any(not isinstance(path, str) or approved_path(path, (ROOT_PAIRS['models'][1],)) != path
                               for path in config['model_roots'])):
                    raise ValueError('shared_configuration_requires_canonical_library_paths')
            validate_mount(mount_info('/data/share'))  # Fail closed before reading targets.
            PUBLIC_ROOTS = [pathlib.Path(path) for path in new_roots]
            if mode == 'destination_verification':
                prepared['paths'] = [destination_path(path) for path in config['paths']]
                prepared['model_roots'] = [destination_path(path) for path in config['model_roots']]
            else:
                # A nested local mount or a root alias to another filesystem
                # must not produce a successful shared-library snapshot.
                for root in new_roots:
                    validate_mount(mount_info(root))
                    if os.path.realpath(root) != root:
                        raise ValueError('shared_library_root_must_be_canonical')
        result = _collect(prepared)
        result['location_mode'] = mode
        return result
    finally:
        PUBLIC_ROOTS = old_roots


def _collect(config):
    started = time.monotonic()
    if any(not in_scope(p) for p in config['paths'] + config['model_roots']):
        raise ValueError('collection_configuration_outside_public_roots')
    if any(not safe_path(p) for p in config['model_roots']):
        raise ValueError('model_root_target_outside_public_roots')
    paths = {p: check(p) for p in config['paths']}
    models, errors, seen, discovered = [], [], set(), []
    allowed_roots = [pathlib.Path(p).resolve(strict=True) for p in config['model_roots']]
    directories = 0
    # Shallow directory inventory gives every public branch an entry without
    # opening records, walking all samples, hashing bytes, or running du.
    stack = [(str(root), 0) for root in PUBLIC_ROOTS]
    while stack:
        path, depth = stack.pop()
        if not safe_path(path):
            errors.append({'root':path,'reason':'outside_public_roots'})
            continue
        if directories >= 20000 or time.monotonic() - started > 120:
            errors.append({'root':path,'reason':'scan_budget_reached'})
            break
        paths.setdefault(path, check(path))
        if depth == 3:
            discovered.append({'path':path,'name':pathlib.Path(path).name,
                               'kind':'model' if any(in_scope(path) and pathlib.Path(path).is_relative_to(pathlib.Path(p)) for p in config['model_roots']) else 'dataset',
                               'stat':paths[path], 'depth':depth})
            continue
        try:
            with os.scandir(path) as it:
                entries = list(itertools.islice(it, 10001))
            directories += 1
            if len(entries) > 10000:
                errors.append({'root':path,'reason':'directory_entry_limit','limit':10000})
            children = []
            for entry in entries[:10000]:
                if entry.name in IGNORE:
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        children.append(entry.path)
                    elif entry.is_symlink():
                        if not safe_path(entry.path):
                            errors.append({'root':path,'reason':'external_symlink_skipped'})
                        else:
                            paths.setdefault(entry.path,check(entry.path))
                            discovered.append({'path':entry.path,'name':entry.name,
                                               'kind':'model' if any(pathlib.Path(path).is_relative_to(pathlib.Path(p)) for p in config['model_roots']) else 'dataset',
                                               'stat':paths[entry.path], 'depth':depth+1,'symlink':True})
                except OSError:
                    errors.append({'root':path,'reason':'entry_type_unreadable'})
            if depth == 3 or not children:
                discovered.append({'path':path,'name':pathlib.Path(path).name,
                                   'kind':'model' if any(pathlib.Path(path).is_relative_to(pathlib.Path(p)) for p in config['model_roots']) else 'dataset',
                                   'stat':paths[path], 'depth':depth})
            else:
                stack.extend((p,depth+1) for p in children)
                # A container may also hold files; retain it as a coverage node.
                discovered.append({'path':path,'name':pathlib.Path(path).name,
                                   'kind':'model' if any(pathlib.Path(path).is_relative_to(pathlib.Path(p)) for p in config['model_roots']) else 'dataset',
                                   'stat':paths[path], 'depth':depth,'container':True})
        except OSError as e:
            errors.append({'root':path,'reason':type(e).__name__})
            discovered.append({'path':path,'name':pathlib.Path(path).name,
                               'kind':'model' if any(pathlib.Path(path).is_relative_to(pathlib.Path(p)) for p in config['model_roots']) else 'dataset',
                               'stat':paths[path], 'depth':depth})
    for root in config['model_roots']:
        stack = [(root, 0)]
        while stack:
            path, depth = stack.pop()
            if directories >= 20000 or time.monotonic() - started > 120:
                errors.append({'root': root, 'reason': 'scan_budget_reached'})
                break
            real = os.path.realpath(path)
            if not safe_path(path):
                errors.append({'root':path,'reason':'outside_public_roots'})
                continue
            if real in seen:
                continue
            seen.add(real)
            try:
                with os.scandir(path) as it:
                    entries = list(itertools.islice(it, 10001))
                capped = len(entries) > 10000
                if capped:
                    entries = entries[:10000]
                    errors.append({'root':path, 'reason':'directory_entry_limit', 'limit':10000})
                directories += 1
            except OSError as e:
                errors.append({'root': path, 'reason': type(e).__name__})
                continue
            names = {e.name for e in entries}
            files, subdirs = [], []
            for e in entries:
                try:
                    if not safe_path(e.path):
                        errors.append({'root':path,'reason':'external_symlink_skipped'})
                    elif e.is_file():
                        files.append(e)
                    elif e.is_dir(follow_symlinks=False):
                        subdirs.append(e)
                except OSError:
                    errors.append({'root':path,'reason':'entry_type_unreadable'})
            weight_entries = [e for e in files if pathlib.Path(e.name).suffix.lower() in WEIGHTS]
            is_model = bool(weight_entries) and ('config.json' in names or depth <= 1 or 'snapshots' in path)
            if is_model:
                formats = collections.Counter(pathlib.Path(e.name).suffix.lower() for e in weight_entries)
                cfg = {}
                cp = pathlib.Path(path) / 'config.json'
                try:
                    if cp.exists():
                        raw = read_config(cp, allowed_roots)
                        cfg = {k: raw[k] for k in ['model_type', 'architectures', 'torch_dtype', 'dtype', 'hidden_size', 'num_hidden_layers', 'vocab_size', 'transformers_version'] if k in raw}
                        if not isinstance(cfg.get('architectures', []), list):
                            cfg.pop('architectures', None)
                        elif 'architectures' in cfg:
                            cfg['architectures'] = [a for a in cfg['architectures'] if isinstance(a, str)]
                except (OSError, ValueError):
                    errors.append({'root': path, 'reason': 'config_unreadable'})
                sizes, stat_errors = [], 0
                for e in files:
                    try: sizes.append(e.stat().st_size)
                    except OSError:
                        stat_errors += 1
                if stat_errors:
                    errors.append({'root':path,'reason':'file_stat_failed','count':stat_errors})
                item = {'path': path, 'name': pathlib.Path(path).name, 'root': root,
                        'file_count': None if capped else len(files), 'weight_file_count': len(weight_entries), 'size_bytes': None if capped or stat_errors else sum(sizes),
                        'metadata_complete':not (capped or stat_errors),
                        'formats': list(formats), 'config': cfg, 'stat': check(path),
                        'revision': pathlib.Path(path).name if '/snapshots/' in path else None,
                        'completeness': 'weights_present_not_loaded'}
                if '/models--' in path:
                    item['name'] = path.split('/models--',1)[1].split('/')[0].replace('--','/')
                models.append(item)
                paths[path] = item['stat']
                # Do not descend into model internals or optimizer files.
                continue
            if depth < 5:
                for e in subdirs:
                    if e.name not in IGNORE and not e.name.startswith('.'):
                        stack.append((e.path, depth + 1))
    # Evaluate runtime access with the actual Unix user and groups, independently of admin stat.
    code = "import json,os,sys; p=json.load(sys.stdin); print(json.dumps({x:os.access(x,os.R_OK|(os.X_OK if os.path.isdir(x) else 0)) for x in p}))"
    access_paths = [p for p in paths if paths[p].get('reason') != 'outside_public_roots']
    proc = subprocess.run(['sudo','-u','rmp','--','/usr/bin/python3','-c',code], input=json.dumps(access_paths), text=True, capture_output=True, check=True, timeout=15)
    access = json.loads(proc.stdout)
    for p,v in paths.items():
        v['rmp_readable'] = access.get(p, False)
    disks = {}
    for root in PUBLIC_ROOTS:
        mount = mount_info(root)
        if mount['target'] not in disks:
            st = os.statvfs(root)
            disks[mount['target']] = {'mount':mount['target'], 'source':mount['source'], 'filesystem':mount['fstype'],
                                     'total_bytes':st.f_blocks*st.f_frsize,'available_bytes':st.f_bavail*st.f_frsize}
    return {'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'host': config.get('host', '101.132.97.146'),
            'method': 'admin path stat + bounded model directory metadata; runtime access tested as rmp',
            'path_checks': paths, 'models': models, 'collections':discovered,'errors': errors,
            'model_roots': config['model_roots'], 'visited_directories': directories,
            'disk': next(iter(disks.values()), {}), 'disk_snapshots': list(disks.values()),
            'limits': {'public_roots':[str(p) for p in PUBLIC_ROOTS], 'dataset_depth':3,'max_depth':5,'max_directories':20000,'max_seconds':120,'weights_loaded':False,'data_content_opened':False,'sizes':'direct files only for model directories; internal symlink target sizes included; not unique disk usage'}}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('config')
    args = parser.parse_args()
    print(json.dumps(collect(json.loads(pathlib.Path(args.config).read_text())), ensure_ascii=False))
