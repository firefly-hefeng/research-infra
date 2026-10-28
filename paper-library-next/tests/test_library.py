import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from paperlib.library import Library, digest
from paperlib.worker import run_batch, configuration


def pdf_bytes(text='Test Paper by Alice. A 2024 study uses useful data selection to improve model quality. The contribution is a verified experiment.'):
    stream = f'BT /F1 12 Tf 40 700 Td ({text}) Tj ET'.encode()
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1600 800] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    result = b'%PDF-1.4\n'; offsets = []
    for i,obj in enumerate(objects):
        offsets.append(len(result)); result += f'{i+1} 0 obj\n'.encode()+obj+b'\nendobj\n'
    xref = len(result)
    result += b'xref\n0 6\n0000000000 65535 f \n'+b''.join(f'{o:010} 00000 n \n'.encode() for o in offsets)
    result += f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    return result


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'papers'
        self.lib = Library(self.root)
        self.source = self.root / 'inbox' / 'test.pdf'
        self.source.write_bytes(pdf_bytes())
        self.id = digest(self.source)
        self.lib.scan(settle_seconds=0)
        self.text = self.lib.extract(self.id)

    def tearDown(self):
        self.tmp.cleanup()

    def card(self):
        return dict(title='Test Paper', authors=['Alice'], year=2024, venue='', category='数据选择',
                    tags=['数据选择'], summary='以数据选择提高模型质量。', contributions=['进行了可核对的实验。'],
                    limitations=[], needs_review=False, review_reason='',
                    evidence=[dict(field=f, page=1, quote=self.text.strip()) for f in ('title','authors','year','summary','contributions')])

    def test_archive_hash_and_restart(self):
        result = self.lib.commit(self.id, self.card())
        self.assertEqual(result['status'], 'ready'); self.assertFalse(self.source.exists())
        self.assertEqual(digest(self.lib.pdf_path(self.id)), self.id)
        self.assertEqual(Library(self.root).record(self.id)['card']['title'], 'Test Paper')
        self.assertEqual(json.loads(self.lib.pdf_path(self.id).with_name('card.json').read_text())['title'], 'Test Paper')

    def test_duplicate_retained_without_extra_card(self):
        self.lib.commit(self.id, self.card()); self.source.write_bytes(pdf_bytes())
        result = self.lib.scan(settle_seconds=0)
        self.assertEqual(result['duplicates'], 1); self.assertEqual(len(self.lib.papers()), 1)
        self.assertEqual(digest(self.root/'duplicates'/self.id/'test.pdf'), self.id)

    def test_root_import_preserves_original_and_is_idempotent(self):
        original = self.root/'original.pdf'; original.write_bytes(pdf_bytes('Another original paper for a separate scientific project. It contains enough useful text for extraction and indexing.'))
        self.assertEqual(len(self.lib.bootstrap()), 1); self.lib.scan(settle_seconds=0)
        self.assertEqual(self.lib.bootstrap(), []); self.assertTrue(original.exists())

    def test_invalid_evidence_keeps_source(self):
        card = self.card(); card['evidence'][0]['quote'] = 'invented claim absent from document'
        with self.assertRaises(ValueError): self.lib.commit(self.id, card)
        self.assertTrue(self.source.exists()); self.assertEqual(self.lib.record(self.id)['status'], 'pending')

    def test_missing_evidence_and_invalid_year_rejected(self):
        card=self.card(); card['evidence']=[]
        with self.assertRaises(ValueError): self.lib.commit(self.id,card)
        card=self.card(); card['year']=True
        with self.assertRaises(ValueError): self.lib.commit(self.id,card)

    def test_unknown_year_is_review(self):
        card = self.card(); card['year'] = None; card['review_reason'] = '年份待核对'
        self.assertEqual(self.lib.commit(self.id, card)['status'], 'review')

    def test_notes_survive_recuration(self):
        self.lib.commit(self.id,self.card()); self.lib.edit(self.id, {'notes':'需要比较目标协方差。', 'favorite': True})
        self.lib.commit(self.id,self.card()); restarted=Library(self.root).record(self.id)
        self.assertTrue(restarted['favorite']); self.assertIn('协方差',restarted['notes'])

    def test_modified_source_cannot_be_committed(self):
        self.source.write_bytes(pdf_bytes('The source has changed.'))
        with self.assertRaises(ValueError): self.lib.commit(self.id,self.card())
        self.assertTrue(self.source.exists())

    def test_symlinks_and_path_escape_rejected(self):
        outside = Path(self.tmp.name)/'outside.pdf'; outside.write_bytes(pdf_bytes())
        (self.root/'inbox'/'link.pdf').symlink_to(outside)
        self.assertEqual(self.lib.scan(settle_seconds=0)['added'],0)
        for path in ['../outside.pdf',str(outside),'inbox/link.pdf']:
            with self.assertRaises(ValueError): self.lib.safe(path)
        with self.assertRaises(ValueError): self.lib.record('../../etc/passwd')

    def test_archive_directory_symlink_rejected(self):
        outside=Path(self.tmp.name)/'outside'; outside.mkdir(); (self.root/'library'/'数据选择').symlink_to(outside)
        with self.assertRaises(ValueError): self.lib.commit(self.id,self.card())
        self.assertTrue(self.source.exists()); self.assertEqual(list(outside.iterdir()),[])

    def test_unfinished_copy_is_not_scanned(self):
        extra=self.root/'inbox'/'fresh.pdf'; extra.write_bytes(pdf_bytes('A different paper.'))
        result=self.lib.scan(settle_seconds=30)
        self.assertEqual(result['added'],0); self.assertTrue(result['skipped'])

    def test_invalid_pdf_and_ocr_failures(self):
        extra=self.root/'inbox'/'bad.pdf'; extra.write_bytes(b'not really pdf'); self.lib.scan(settle_seconds=0)
        with self.assertRaises(ValueError): self.lib.extract(digest(extra))
        extra=self.root/'inbox'/'blank.pdf'; extra.write_bytes(pdf_bytes('')); self.lib.scan(settle_seconds=0)
        with self.assertRaises(ValueError): self.lib.extract(digest(extra))

    def test_manual_cli(self):
        result=subprocess.run([sys.executable,'manage.py','--root',str(self.root),'list'],capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(result.stdout)[0]['id'],self.id)

    def test_agent_batch_success_and_failure_logs(self):
        fake=Path(self.tmp.name)/'agent.py'; card=self.card()
        fake.write_text('import json,sys\njob=json.load(sys.stdin)\nassert job["paper_id"]\nprint('+repr(json.dumps(card))+')\n')
        result=run_batch(self.lib,[sys.executable,str(fake)])
        self.assertEqual(result['completed'],1); self.assertEqual(self.lib.jobs()[0]['status'],'completed')
        extra=self.root/'inbox'/'bad.pdf'; extra.write_bytes(pdf_bytes('A second paper about optimization. This experiment has enough readable text to be indexed and summarized correctly.')); os.utime(extra,(0,0))
        fake.write_text('print("not JSON")'); result=run_batch(self.lib,[sys.executable,str(fake)])
        self.assertEqual(result['failed'],1); self.assertTrue(extra.exists()); self.assertEqual(self.lib.jobs()[0]['status'],'failed')

    def test_exclusive_agent_lock(self):
        with self.lib.lock('agent',blocking=False):
            with self.assertRaises(BlockingIOError): run_batch(self.lib,[sys.executable,'-c','print("{}")'])

    def test_schedule_off_until_operator_configures(self):
        with patch.dict(os.environ, {'PAPER_AGENT_COMMAND':'','PAPER_SCHEDULE_ENABLED':'1'},clear=False):
            self.assertFalse(configuration()['enabled'])
            with self.assertRaises(ValueError): run_batch(self.lib)

if __name__ == '__main__': unittest.main()
