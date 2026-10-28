"""Explicit, idempotent bibliography import. No model calls or card validation bypass."""
import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from .library import Library, digest, now

MAX_PDF = 256 * 1024 * 1024
HEX = re.compile(r'^[a-f0-9]{64}$')


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field')
        result[key] = value
    return result


def clean_metadata(value):
    if not isinstance(value, dict):
        raise ValueError('metadata must be an object')
    clean = {}
    for key, maximum in [('title', 600), ('venue', 200), ('doi', 200),
                         ('summary', 5000), ('category', 100)]:
        text = value.get(key, '')
        if not isinstance(text, str) or len(text) > maximum or '\x00' in text:
            raise ValueError('Invalid metadata field: ' + key)
        clean[key] = text.strip()
    if not clean['title']:
        raise ValueError('A recorded title is required')
    for key, count, length in [('authors', 100, 600), ('tags', 12, 60), ('source_record_ids', 50, 100)]:
        items = value.get(key, [])
        if not isinstance(items, list) or len(items) > count or any(
                not isinstance(x, str) or not x.strip() or len(x) > length or '\x00' in x for x in items):
            raise ValueError('Invalid list: ' + key)
        clean[key] = list(dict.fromkeys(items))
    year = value.get('year')
    if year is not None and (type(year) is not int or not 1800 <= year <= 2100):
        raise ValueError('Invalid publication year')
    clean['year'] = year
    sources = value.get('provenance', [])
    if not isinstance(sources, list) or not 1 <= len(sources) <= 10:
        raise ValueError('Bibliographic provenance is required')
    clean['provenance'] = []
    for source in sources:
        if not isinstance(source, dict) or set(source) - {'label', 'sha256', 'record_id'}:
            raise ValueError('Only public provenance labels and digests are permitted')
        if not isinstance(source.get('label'), str) or not 1 <= len(source['label']) <= 300:
            raise ValueError('Invalid provenance label')
        if not isinstance(source.get('sha256'), str) or not HEX.fullmatch(source['sha256']):
            raise ValueError('Invalid source digest')
        if 'record_id' in source and (not isinstance(source['record_id'], str) or len(source['record_id']) > 100):
            raise ValueError('Invalid source record id')
        clean['provenance'].append(dict(source))
    # Import never claims PDF-grounded interpretation or authorizes redistribution.
    clean['review_state'] = 'bibliography_only'
    clean['fulltext_policy'] = 'restricted'
    return clean


def regular(path, root):
    if not path.is_relative_to(root):
        raise ValueError('Path outside bundle')
    for parent in [path, *path.parents]:
        if parent.is_symlink():
            raise ValueError('Symlinks are forbidden in a bundle path')
        if parent == root:
            break
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('Bundle objects must be ordinary files')
    return info


def validate_bundle(folder):
    root = Path(folder).absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Bundle must be a real directory')
    root = root.resolve()
    manifest_path = root / 'manifest.json'
    if regular(manifest_path, root).st_size > 16 * 1024 * 1024:
        raise ValueError('Manifest exceeds 16 MiB')
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw, object_pairs_hook=strict_object)
    if manifest.get('schema_version') != '1.0':
        raise ValueError('Unsupported bundle schema')
    collection = manifest.get('collection_id')
    if not isinstance(collection, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,95}', collection):
        raise ValueError('Invalid collection ID')
    items = manifest.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= 2000:
        raise ValueError('A bundle needs 1–2000 PDF objects')
    clean, seen = [], set()
    for item in items:
        ident = item.get('id') if isinstance(item, dict) else None
        if not isinstance(ident, str) or not HEX.fullmatch(ident) or ident in seen:
            raise ValueError('Invalid or repeated content identity')
        seen.add(ident)
        if item.get('pdf') != 'objects/' + ident + '.pdf':
            raise ValueError('Object paths must be content-addressed')
        filename = item.get('filename')
        if not isinstance(filename, str) or not 1 <= len(filename) <= 600 or any(c in filename for c in '/\\\x00'):
            raise ValueError('Invalid original filename')
        source = root / item['pdf']
        before = regular(source, root)
        if type(item.get('size_bytes')) is not int or not 1 <= before.st_size == item['size_bytes'] <= MAX_PDF:
            raise ValueError('Invalid PDF byte count')
        with source.open('rb') as stream:
            if not stream.read(8).startswith(b'%PDF-'):
                raise ValueError('Object is not a PDF')
        if digest(source) != ident:
            raise ValueError('Object checksum mismatch')
        after = regular(source, root)
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError('Object changed during validation')
        clean.append({'id': ident, 'source': source, 'filename': filename,
                      'size_bytes': before.st_size, 'metadata': clean_metadata(item.get('metadata'))})
    return {'root': root, 'collection_id': collection, 'items': clean,
            'manifest_sha256': hashlib.sha256(raw).hexdigest()}


def import_bundle(library, folder):
    bundle = validate_bundle(folder)  # All checks precede any imported writes.
    report = {'collection_id': bundle['collection_id'], 'manifest_sha256': bundle['manifest_sha256'],
              'added': 0, 'existing_untouched': 0, 'bytes_copied': 0, 'fulltext_policy': 'restricted'}
    with library.lock():
        for item in bundle['items']:
            with library.db() as db:
                exists = db.execute('SELECT 1 FROM papers WHERE id=?', (item['id'],)).fetchone()
            if exists:
                report['existing_untouched'] += 1
                continue
            relative = 'inbox/imported/' + bundle['collection_id'] + '/' + item['id'] + '.pdf'
            dest = library.safe(relative)
            dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            dest = library.safe(relative)
            if dest.exists():
                if digest(dest) != item['id']:
                    raise ValueError('Import destination already has different bytes')
            else:
                handle, temporary = tempfile.mkstemp(prefix='.import-', suffix='.part', dir=dest.parent)
                temporary = Path(temporary)
                try:
                    h = hashlib.sha256()
                    with os.fdopen(handle, 'wb') as target, item['source'].open('rb') as source:
                        for block in iter(lambda: source.read(1024 * 1024), b''):
                            target.write(block)
                            h.update(block)
                        target.flush()
                        os.fsync(target.fileno())
                    if temporary.stat().st_size != item['size_bytes'] or h.hexdigest() != item['id']:
                        raise ValueError('Source changed while copying')
                    os.chmod(temporary, 0o600)
                    os.link(temporary, dest)  # Refuse an unexpected concurrently created destination.
                    report['bytes_copied'] += item['size_bytes']
                finally:
                    temporary.unlink(missing_ok=True)
            timestamp = now()
            with library.db() as db:
                db.execute('INSERT INTO papers(id,filename,source,status,created,updated) VALUES(?,?,?,?,?,?)',
                    (item['id'], item['filename'], relative, 'bibliography', timestamp, timestamp))
                db.execute('INSERT INTO bibliographic_imports(paper_id,collection_id,metadata,manifest_sha256,imported_at) VALUES(?,?,?,?,?)',
                    (item['id'], bundle['collection_id'], json.dumps(item['metadata'], ensure_ascii=False),
                     bundle['manifest_sha256'], timestamp))
            report['added'] += 1
    return report


def main():
    parser = argparse.ArgumentParser(description='Explicit bibliography bundle check/import; no Agent or API execution')
    parser.add_argument('command', choices=['check', 'import'])
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--root', help='Explicit existing or new paper library root; required for import')
    args = parser.parse_args()
    if args.command == 'check':
        bundle = validate_bundle(args.bundle)
        result = {'valid': True, 'collection_id': bundle['collection_id'],
                  'manifest_sha256': bundle['manifest_sha256'], 'unique_pdfs': len(bundle['items']),
                  'bytes': sum(x['size_bytes'] for x in bundle['items'])}
    else:
        if not args.root:
            parser.error('--root is required for import')
        validate_bundle(args.bundle)  # Do not create a library for an invalid bundle.
        result = import_bundle(Library(args.root), args.bundle)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
