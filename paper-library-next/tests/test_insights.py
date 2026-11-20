import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from paperlib.insights import import_insights, public_insight, read_insight, source_text, validate_insight
from paperlib.library import Library, digest
from paperlib.server import catalog_paper
from test_library import pdf_bytes


def multipage_pdf(texts):
    """Small real PDFs keep extraction/page validation exercised end to end."""
    font_id = 3 + 2 * len(texts)
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               ('<< /Type /Pages /Kids [' + ' '.join(str(3 + 2 * i) + ' 0 R' for i in range(len(texts))) +
                '] /Count ' + str(len(texts)) + ' >>').encode()]
    for i, text in enumerate(texts):
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1600 800] /Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {4 + 2 * i} 0 R >>'.encode())
        stream = f'BT /F1 12 Tf 40 700 Td ({text}) Tj ET'.encode()
        objects.append(b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream')
    objects.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    result, offsets = b'%PDF-1.4\n', []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result += f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n'
    start = len(result)
    result += f'xref\n0 {len(objects) + 1}\n0000000000 65535 f \n'.encode()
    result += b''.join(f'{offset:010} 00000 n \n'.encode() for offset in offsets)
    return result + f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()


class InsightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'papers'
        self.library = Library(self.root)
        self.pdf = self.root / 'inbox' / 'source.pdf'
        self.pdf.write_bytes(pdf_bytes())
        self.ident = digest(self.pdf)
        self.library.scan(settle_seconds=0)
        self.text = source_text(self.library, self.ident).strip()

    def tearDown(self):
        self.temp.cleanup()

    def insight(self):
        return {'schema_version': 1, 'source_digest': self.ident,
                'abstract': {'status': 'available', 'text': self.text, 'language': 'en', 'pages': [1]},
                'keywords': ['数据选择', '模型质量', '实验验证'],
                'summary': {'overview': '这项研究使用数据选择方法改善模型质量，并报告可核对的实验。',
                            'problem': '', 'method': '', 'findings': '', 'limitations': ''},
                'evidence': [{'field': 'summary.overview', 'page': 1, 'quote': self.text}],
                'coverage': 'abstract', 'generated_by': 'codex'}

    def table_snapshot(self):
        with self.library.db() as db:
            return {table: [tuple(row) for row in db.execute('SELECT * FROM ' + table)]
                    for table in ('papers', 'bibliographic_imports', 'jobs', 'settings')}

    def test_commit_preserves_original_record_pdf_notes_and_classification(self):
        self.library.edit(self.ident, {'notes': '团队笔记应保留', 'favorite': True})
        with self.library.db() as db:
            db.execute('INSERT INTO bibliographic_imports VALUES(?,?,?,?,?)',
                       (self.ident, 'collection', json.dumps({'title': 'Imported', 'category': '原有分类'}), 'a' * 64, '2026-01-01'))
        before = self.table_snapshot()
        saved = self.library.commit_insight(self.ident, self.insight())
        self.assertTrue(saved['changed'])
        self.assertEqual(self.table_snapshot(), before)
        self.assertTrue(self.pdf.is_file())
        self.assertEqual(digest(self.pdf), self.ident)
        record = Library(self.root).record(self.ident)
        self.assertEqual(record['insight']['abstract']['text'], self.text)
        self.assertEqual(record['insight']['keywords_source'], 'curated')
        self.assertIsNone(record['card'])
        self.assertEqual(record['bibliography']['category'], '原有分类')
        self.assertEqual(record['notes'], '团队笔记应保留')

    def test_repeat_is_idempotent_and_invalid_replacement_preserves_previous(self):
        first = self.library.commit_insight(self.ident, self.insight())
        second = self.library.commit_insight(self.ident, self.insight())
        self.assertFalse(second['changed'])
        self.assertEqual(first['insight'], second['insight'])
        bad = self.insight()
        bad['abstract']['text'] = 'This invented abstract does not occur in the document.'
        with self.assertRaises(ValueError):
            self.library.commit_insight(self.ident, bad)
        self.assertEqual(self.library.record(self.ident)['insight'], first['insight'])

    def test_identity_and_source_bytes_are_bound(self):
        for key in ('paper_id', 'source_digest'):
            bad = self.insight()
            bad[key] = 'b' * 64
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.library.commit_insight(self.ident, bad)
        self.pdf.write_bytes(pdf_bytes('The PDF bytes have changed but the identifier has not.'))
        with self.assertRaises(ValueError):
            self.library.commit_insight(self.ident, self.insight())
        self.assertIsNone(self.library.record(self.ident)['insight'])

    def test_each_nonempty_summary_field_needs_literal_page_evidence(self):
        for field in ('problem', 'method', 'findings', 'limitations'):
            candidate = self.insight()
            candidate['summary'][field] = '这段中文概括必须提供对应的原文证据。'
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_insight(self.library, self.ident, candidate)
            candidate['evidence'].append({'field': 'summary.' + field, 'page': 1, 'quote': self.text})
            self.assertTrue(validate_insight(self.library, self.ident, candidate)['summary'][field])
        for change in ({'page': 2}, {'quote': 'The paper proves a fabricated finding.'}):
            bad = self.insight()
            bad['evidence'][0].update(change)
            with self.assertRaises(ValueError):
                validate_insight(self.library, self.ident, bad)

    def test_abstract_cannot_be_translation_or_ellipsis_or_reordered_pages(self):
        for abstract in (
            {'text': '这是翻译后的中文摘要，不能代替原文摘要中的完整表述。'},
            {'text': self.text[:40] + ' ... ' + self.text[-30:]},
            {'pages': [0]}, {'pages': [True]}, {'pages': [1, 1]},
            {'pages': [2, 1]}, {'language': 'unknown'}):
            bad = self.insight()
            bad['abstract'].update(abstract)
            with self.subTest(abstract=abstract), self.assertRaises(ValueError):
                validate_insight(self.library, self.ident, bad)

    def test_cross_page_abstract_matches_contiguous_reading_order(self):
        self.pdf.write_bytes(multipage_pdf([
            'Abstract. This work studies data selection for reliable model quality.',
            'It evaluates the method with verified experiments under fixed conditions.']))
        ident = digest(self.pdf)
        self.library.scan(settle_seconds=0)
        pages = source_text(self.library, ident).split('\f')
        value = self.insight()
        value['source_digest'] = ident
        value['abstract'].update(text='\n'.join(page.strip() for page in pages[:2]), pages=[1, 2])
        value['evidence'][0].update(page=2, quote=pages[1].strip())
        saved = self.library.commit_insight(ident, value)
        self.assertEqual(saved['insight']['abstract']['pages'], [1, 2])

    def test_missing_abstract_is_explicit_and_does_not_force_invention(self):
        value = self.insight()
        value['abstract'] = {'status': 'missing', 'reason': '此文件没有独立摘要段落。'}
        value['summary'] = {}
        value['keywords'] = []
        value['evidence'] = []
        with patch('paperlib.insights.source_text', side_effect=AssertionError('No extraction needed')):
            saved = self.library.commit_insight(self.ident, value)
        self.assertFalse(any(saved['insight']['summary'].values()))
        value['abstract']['text'] = self.text
        with self.assertRaises(ValueError):
            validate_insight(self.library, self.ident, value)

    def test_plain_text_cache_does_not_replace_layout_card_evidence(self):
        legacy = self.root / '.paperlib' / 'text' / (self.ident + '.txt')
        legacy.write_text('Legacy layout contents must remain intact.', encoding='utf-8')
        actual = source_text(self.library, self.ident)
        self.assertIn('Test Paper by Alice', actual)
        self.assertEqual(legacy.read_text(), 'Legacy layout contents must remain intact.')
        plain = self.root / '.paperlib' / 'insights' / 'source' / (self.ident + '.txt')
        self.assertEqual(plain.stat().st_mode & 0o777, 0o600)

    def test_shape_and_language_limits(self):
        mutations = [
            lambda x: x.update(schema_version=True),
            lambda x: x.update(keywords=['only-one']),
            lambda x: x.update(keywords=['AI', 'ai', '模型']),
            lambda x: x.update(keywords_source='author'),
            lambda x: x.update(generated_by='unknown-tool'),
            lambda x: x.update(coverage='unlimited'),
            lambda x: x['summary'].update(overview='English instead of a Chinese explanation.'),
            lambda x: x['summary'].update(overview=''),
            lambda x: x.update(secret='/private/credential')]
        for mutate in mutations:
            bad = self.insight()
            mutate(bad)
            with self.assertRaises(ValueError):
                validate_insight(self.library, self.ident, bad)

    def test_public_catalog_exposes_insight_without_private_fields(self):
        self.library.commit_insight(self.ident, self.insight())
        record = self.library.record(self.ident)
        record['insight'].update(private_path='/private/file')
        record['insight']['abstract']['local_cache'] = '/private/cache'
        record['insight']['summary']['source'] = '/private/source'
        record['insight']['evidence'][0]['filepath'] = '/private/page'
        public = catalog_paper(record)
        self.assertNotIn('/private/', json.dumps(public))
        self.assertEqual(public['insight']['summary']['overview'], self.insight()['summary']['overview'])
        self.assertIsNone(public_insight(None))

    def test_batch_check_import_idempotency_and_failed_item_log(self):
        folder = Path(self.temp.name) / 'batch'
        folder.mkdir()
        (folder / (self.ident + '.json')).write_text(json.dumps(self.insight()))
        (folder / ('b' * 64 + '.json')).write_text(json.dumps(self.insight()))
        checked = import_insights(self.library, folder, check=True)
        self.assertEqual((checked['valid'], checked['failed'], checked['saved']), (1, 1, 0))
        self.assertIsNone(self.library.record(self.ident)['insight'])
        saved = import_insights(self.library, folder)
        self.assertEqual((saved['saved'], saved['failed']), (1, 1))
        repeated = import_insights(self.library, folder)
        self.assertEqual((repeated['unchanged'], repeated['failed']), (1, 1))
        log = self.root / repeated['log_file']
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(log.read_text()), repeated)
        result = subprocess.run([sys.executable, 'manage.py', '--root', str(self.root),
                                 'import-insights', str(folder), '--check'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['failed'], 1)

    def test_cli_commit_and_json_file_boundaries(self):
        extracted = subprocess.run([sys.executable, 'manage.py', '--root', str(self.root),
                                    'extract-insight', self.ident], capture_output=True, text=True, check=True)
        self.assertEqual(extracted.stdout.strip(), self.text)
        path = Path(self.temp.name) / (self.ident + '.json')
        path.write_text(json.dumps(self.insight()))
        result = subprocess.run([sys.executable, 'manage.py', '--root', str(self.root),
                                 'commit-insight', self.ident, str(path)], capture_output=True, text=True, check=True)
        self.assertTrue(json.loads(result.stdout)['changed'])
        link = path.with_name('link.json')
        link.symlink_to(path)
        with self.assertRaises(ValueError):
            read_insight(link)
        path.write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaises(ValueError):
            read_insight(path)


    def test_abstract_segments_remove_only_matched_page_noise(self):
        first = 'This work examines how examples influence depression assessment.'
        second = 'The results show that relevant context improves prediction quality.'
        self.pdf.write_bytes(multipage_pdf([first + ' Author footer and page number.',
                                           'Journal running header. ' + second]))
        ident = digest(self.pdf)
        self.library.scan(settle_seconds=0)
        value = self.insight()
        value['source_digest'] = ident
        value['abstract'].update(text=first + '\n' + second, pages=[1, 2],
                                 segments=[{'page': 1, 'text': first}, {'page': 2, 'text': second}])
        value['evidence'][0].update(page=2, quote=second)
        saved = self.library.commit_insight(ident, value)
        self.assertEqual(saved['insight']['abstract']['text'], first + '\n' + second)
        self.assertNotIn('footer', saved['insight']['abstract']['text'])
        for change in ('reorder', 'rewrite', 'overlap'):
            bad = json.loads(json.dumps(value))
            if change == 'reorder': bad['abstract']['segments'].reverse()
            if change == 'rewrite': bad['abstract']['text'] += ' invented content'
            if change == 'overlap': bad['abstract']['segments'].insert(0, {'page': 1, 'text': first})
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_insight(self.library, ident, bad)

    def test_confirmed_column_order_preserves_disjoint_source_spans(self):
        first = 'The research investigates a question about depression prediction.'
        second = 'The findings demonstrate improved prediction for the tested sample.'
        self.pdf.write_bytes(pdf_bytes(second + ' ' + first))
        ident = digest(self.pdf)
        self.library.scan(settle_seconds=0)
        value = self.insight()
        value['source_digest'] = ident
        value['abstract'].update(text=first + ' ' + second, segment_order='reading_order',
                                 segments=[{'page': 1, 'text': first}, {'page': 1, 'text': second}])
        value['evidence'][0]['quote'] = first
        self.assertEqual(validate_insight(self.library, ident, value)['abstract']['text'], first + ' ' + second)
        default = json.loads(json.dumps(value))
        del default['abstract']['segment_order']
        with self.assertRaises(ValueError): validate_insight(self.library, ident, default)
        value['abstract']['segments'].append({'page': 1, 'text': first})
        value['abstract']['text'] += first
        with self.assertRaises(ValueError): validate_insight(self.library, ident, value)

    def test_empty_scan_ocr_is_recorded_and_cache_remains_separate(self):
        self.pdf.write_bytes(pdf_bytes(' '))
        ident = digest(self.pdf)
        self.library.scan(settle_seconds=0)
        recognized = 'This is a scanned abstract with source grounded findings.\f'
        with patch('paperlib.insights.ocr_text', return_value=recognized) as ocr:
            self.assertEqual(source_text(self.library, ident), recognized)
            self.assertEqual(source_text(self.library, ident), recognized)
            ocr.assert_called_once()
        value = self.insight()
        value['source_digest'] = ident
        value['abstract'].update(text=recognized.strip(), pages=[1])
        value['evidence'][0].update(quote=recognized.strip())
        self.assertEqual(self.library.commit_insight(ident, value)['insight']['source_method'], 'ocr')


if __name__ == '__main__':
    unittest.main()
