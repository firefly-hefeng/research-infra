import json
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from paperlib.library import Library, digest, title_folder
import test_library as fixtures


class TitleStorageTests(unittest.TestCase):
    setUp = fixtures.LibraryTests.setUp
    tearDown = fixtures.LibraryTests.tearDown
    card = fixtures.LibraryTests.card

    def add_paper(self, suffix):
        path = self.root / 'inbox' / (suffix + '.pdf')
        path.write_bytes(fixtures.pdf_bytes(self.text.strip() + ' ' + suffix))
        self.lib.scan(settle_seconds=0)
        ident = digest(path)
        self.lib.extract(ident)
        return ident

    def legacy(self, ident):
        self.lib.commit(ident, self.card())
        current = self.lib.pdf_path(ident).parent
        old = current.with_name(ident)
        os.rename(current, old)
        with self.lib.db() as db:
            db.execute('UPDATE papers SET pdf=? WHERE id=?', (str((old / 'paper.pdf').relative_to(self.lib.root)), ident))
        return old

    def test_title_and_numbered_collisions_preserve_each_pdf(self):
        ids = [self.id, self.add_paper('version-two'), self.add_paper('version-three')]
        for ident, expected in zip(ids, ['Test Paper', 'Test Paper（1）', 'Test Paper（2）']):
            self.lib.commit(ident, self.card())
            self.assertEqual(self.lib.pdf_path(ident).parent.name, expected)
            self.assertEqual(digest(self.lib.pdf_path(ident)), ident)
        self.lib.commit(ids[1], self.card())
        self.assertEqual(self.lib.pdf_path(ids[1]).parent.name, 'Test Paper（1）')
        self.assertEqual(len(list((self.root / 'library' / '数据选择' / '2024').iterdir())), 3)

    def test_safe_unicode_names_and_long_titles(self):
        for title in ['../../A/B\\C: D?*<>|"', '\x00\n... ', 'CON', 'LPT1.txt', '中文论文' * 150]:
            with self.subTest(title=title):
                name = title_folder(title, 2)
                self.assertNotIn('/', name)
                self.assertNotIn('\\', name)
                self.assertLessEqual(len(name.encode('utf-8')), 240)
                self.assertTrue(name.endswith('（2）'))
                self.assertFalse(name.startswith('.'))
        card = self.card()
        card['title'] = '研究/分析: 一种方法'
        self.lib.commit(self.id, card)
        self.assertEqual(self.lib.pdf_path(self.id).parent.name, '研究 - 分析 - 一种方法')
        self.assertEqual(self.lib.record(self.id)['card']['title'], card['title'])

    def test_collisions_include_files_symlinks_and_case(self):
        parent = self.root / 'library' / '数据选择' / '2024'
        parent.mkdir(parents=True)
        (parent / 'test paper').write_text('keep')
        (parent / 'Test Paper（1）').mkdir()
        outside = Path(self.tmp.name) / 'outside'
        outside.mkdir()
        (parent / 'Test Paper（2）').symlink_to(outside)
        self.lib.commit(self.id, self.card())
        self.assertEqual(self.lib.pdf_path(self.id).parent.name, 'Test Paper（3）')
        self.assertEqual((parent / 'test paper').read_text(), 'keep')
        self.assertEqual(list(outside.iterdir()), [])

    def test_concurrent_commits_get_distinct_title_folders(self):
        second = self.add_paper('second')
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.lib.commit, ident, self.card()) for ident in (self.id, second)]
            for future in futures:
                future.result()
        names = {self.lib.pdf_path(ident).parent.name for ident in (self.id, second)}
        self.assertEqual(names, {'Test Paper', 'Test Paper（1）'})

    def test_legacy_migration_preserves_metadata_and_is_idempotent(self):
        second = self.add_paper('second')
        olds = [self.legacy(ident) for ident in (self.id, second)]
        self.lib.edit(self.id, {'notes': 'keep notes', 'favorite': True})
        cards = {ident: self.lib.pdf_path(ident).with_name('card.json').read_bytes() for ident in (self.id, second)}
        result = self.lib.migrate_title_directories()
        self.assertEqual(result['moved'], 2)
        self.assertTrue(all(not old.exists() for old in olds))
        self.assertEqual({self.lib.pdf_path(i).parent.name for i in (self.id, second)}, {'Test Paper', 'Test Paper（1）'})
        for ident in (self.id, second):
            self.assertEqual(digest(self.lib.pdf_path(ident)), ident)
            self.assertEqual(self.lib.pdf_path(ident).with_name('card.json').read_bytes(), cards[ident])
        restarted = Library(self.root)
        self.assertEqual(restarted.record(self.id)['notes'], 'keep notes')
        self.assertTrue(restarted.record(self.id)['favorite'])
        self.assertEqual(restarted.migrate_title_directories()['moved'], 0)
        with sqlite3.connect(result['database_backup']) as db:
            original = db.execute('SELECT pdf FROM papers WHERE id=?', (self.id,)).fetchone()[0]
            self.assertEqual(Path(original).parent.name, self.id)
        self.assertEqual(json.loads(Path(result['report']).read_text())['status'], 'completed')

    def test_migration_error_rolls_back_files_and_database(self):
        second = self.add_paper('second')
        olds = [self.legacy(ident) for ident in (self.id, second)]
        original_rename = os.rename
        count = 0
        def fail_second(source, target):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('simulated filesystem error')
            return original_rename(source, target)
        with patch('paperlib.library.os.rename', side_effect=fail_second):
            with self.assertRaises(OSError):
                self.lib.migrate_title_directories()
        for ident, old in zip((self.id, second), olds):
            self.assertTrue(old.exists())
            self.assertEqual(self.lib.pdf_path(ident).parent, old)
        report = next((self.root / '.paperlib' / 'migrations').glob('*-title-directories.json'))
        self.assertEqual(json.loads(report.read_text())['status'], 'rolled_back')

    def test_migration_refuses_active_server_and_changed_pdf(self):
        old = self.legacy(self.id)
        with self.lib.lock('server', blocking=False):
            with self.assertRaises(BlockingIOError):
                self.lib.migrate_title_directories()
        (old / 'paper.pdf').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, '哈希'):
            self.lib.migrate_title_directories()
        self.assertTrue(old.exists())


if __name__ == '__main__':
    unittest.main()
