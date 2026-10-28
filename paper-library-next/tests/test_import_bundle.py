import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from paperlib.import_bundle import import_bundle, validate_bundle
from paperlib.library import Library, digest
from test_library import pdf_bytes


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.bundle = self.base / 'bundle'
        (self.bundle / 'objects').mkdir(parents=True)
        raw = pdf_bytes()
        self.ident = hashlib.sha256(raw).hexdigest()
        (self.bundle / 'objects' / (self.ident + '.pdf')).write_bytes(raw)
        self.manifest = {'schema_version': '1.0', 'collection_id': 'test-collection', 'items': [{
            'id': self.ident, 'pdf': 'objects/' + self.ident + '.pdf', 'filename': 'source.pdf',
            'size_bytes': len(raw), 'metadata': {'title': 'Existing indexed title', 'authors': ['Alice'],
            'year': 2024, 'venue': '', 'doi': '', 'summary': 'Previously recorded description.',
            'category': 'Clinical speech', 'tags': ['speech'], 'source_record_ids': ['A01'],
            'provenance': [{'label': 'Existing source index', 'sha256': 'a' * 64, 'record_id': 'A01'}]}}]}
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        (self.bundle / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')

    def test_import_is_separate_from_validated_cards_and_idempotent(self):
        lib = Library(self.base / 'papers')
        source = self.bundle / self.manifest['items'][0]['pdf']
        result = import_bundle(lib, self.bundle)
        self.assertEqual(result['added'], 1)
        record = lib.record(self.ident)
        self.assertEqual(record['status'], 'bibliography')
        self.assertIsNone(record['card'])
        self.assertEqual(record['bibliography']['fulltext_policy'], 'restricted')
        self.assertEqual(record['bibliography']['title'], 'Existing indexed title')
        self.assertEqual(digest(lib.pdf_path(self.ident)), self.ident)
        self.assertTrue(source.exists())
        lib.edit(self.ident, {'notes': 'Keep this note', 'favorite': True})
        self.manifest['items'][0]['metadata']['title'] = 'Changed incoming metadata'
        self.save()
        result = import_bundle(lib, self.bundle)
        self.assertEqual((result['added'], result['existing_untouched']), (0, 1))
        current = lib.record(self.ident)
        self.assertEqual(current['notes'], 'Keep this note')
        self.assertTrue(current['favorite'])
        self.assertEqual(current['bibliography']['title'], 'Existing indexed title')
        self.assertEqual(lib.scan(settle_seconds=0)['duplicates'], 0)

    def test_existing_record_is_never_overwritten(self):
        lib = Library(self.base / 'papers')
        (lib.root / 'inbox' / 'old.pdf').write_bytes(pdf_bytes())
        lib.scan(settle_seconds=0)
        before = lib.record(self.ident)
        self.assertEqual(import_bundle(lib, self.bundle)['existing_untouched'], 1)
        self.assertEqual(lib.record(self.ident), before)

    def test_hash_mismatch_refused_before_import(self):
        source = self.bundle / self.manifest['items'][0]['pdf']
        source.write_bytes(pdf_bytes('Changed content'))
        with self.assertRaises(ValueError):
            validate_bundle(self.bundle)

    def test_paths_and_symlinks_refused(self):
        item = self.manifest['items'][0]
        item['pdf'] = '../outside.pdf'
        self.save()
        with self.assertRaises(ValueError):
            validate_bundle(self.bundle)
        item['pdf'] = 'objects/' + self.ident + '.pdf'
        self.save()
        source = self.bundle / item['pdf']
        outside = self.base / 'outside.pdf'
        source.rename(outside)
        source.symlink_to(outside)
        with self.assertRaises(ValueError):
            validate_bundle(self.bundle)

    def test_private_provenance_paths_and_invalid_year_rejected(self):
        metadata = self.manifest['items'][0]['metadata']
        metadata['provenance'][0]['source_path'] = '/private/index.json'
        self.save()
        with self.assertRaises(ValueError):
            validate_bundle(self.bundle)
        del metadata['provenance'][0]['source_path']
        metadata['year'] = True
        self.save()
        with self.assertRaises(ValueError):
            validate_bundle(self.bundle)

    def test_unknown_year_preserved_and_policy_cannot_be_granted_by_bundle(self):
        metadata = self.manifest['items'][0]['metadata']
        metadata.update(year=None, fulltext_policy='public', review_state='verified')
        self.save()
        item = validate_bundle(self.bundle)['items'][0]
        self.assertIsNone(item['metadata']['year'])
        self.assertEqual(item['metadata']['fulltext_policy'], 'restricted')
        self.assertEqual(item['metadata']['review_state'], 'bibliography_only')

    def test_duplicate_json_and_duplicate_identity_refused(self):
        path = self.bundle / 'manifest.json'
        path.write_text(path.read_text().replace('"schema_version": "1.0"', '"schema_version": "1.0", "schema_version": "1.0"'))
        with self.assertRaises(ValueError):
            validate_bundle(self.bundle)
        self.manifest['items'].append(self.manifest['items'][0])
        self.save()
        with self.assertRaises(ValueError):
            validate_bundle(self.bundle)

    def test_destination_conflict_is_not_overwritten(self):
        lib = Library(self.base / 'papers')
        dest = lib.root / 'inbox' / 'imported' / 'test-collection' / (self.ident + '.pdf')
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b'other content')
        with self.assertRaises(ValueError):
            import_bundle(lib, self.bundle)
        self.assertEqual(dest.read_bytes(), b'other content')
        self.assertEqual(lib.papers(), [])

    def test_check_cli_does_not_create_library(self):
        target = self.base / 'unused'
        output = subprocess.check_output([sys.executable, '-m', 'paperlib.import_bundle', 'check',
            '--bundle', str(self.bundle), '--root', str(target)], text=True)
        self.assertTrue(json.loads(output)['valid'])
        self.assertFalse(target.exists())

    def test_imported_fulltext_denied_even_without_password(self):
        root = self.base / 'papers'
        import_bundle(Library(root), self.bundle)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = {**os.environ, 'PAPER_PASSWORD': '', 'PAPER_SCHEDULE_ENABLED': '0',
               'PAPER_AGENT_COMMAND': '', 'PAPER_PUBLIC_ORIGIN': ''}
        process = subprocess.Popen([sys.executable, 'manage.py', '--root', str(root), 'serve',
            '--port', str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            base = 'http://127.0.0.1:' + str(port)
            for _ in range(60):
                try:
                    with urlopen(base + '/api/state') as response:
                        data = json.load(response)
                    break
                except URLError:
                    time.sleep(.05)
            else:
                self.fail('Preview server did not start')
            paper = data['papers'][0]
            self.assertIsNone(paper['card'])
            self.assertEqual(paper['bibliography']['review_state'], 'bibliography_only')
            self.assertFalse(paper['fulltext_available'])
            with self.assertRaises(HTTPError) as failure:
                urlopen(base + '/api/papers/' + self.ident + '/pdf')
            self.assertEqual(failure.exception.code, 403)
            failure.exception.close()
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == '__main__':
    unittest.main()
