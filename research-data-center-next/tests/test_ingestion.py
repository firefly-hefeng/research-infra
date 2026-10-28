"""Real local filesystem/SQLite fault tests; production paths are never touched."""
import copy
import dataclasses
import json
import os
from pathlib import Path
import sqlite3
import socket
import stat
import sys
import tempfile
import unittest
from unittest import mock

import ingestion as ing


@unittest.skipUnless(sys.platform.startswith('linux') and os.getuid() != 0,
                     'Needs ordinary Linux account, openat/O_NOFOLLOW and flock')
class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rdc-ingestion-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.share = self.root / 'share'
        self.incoming = self.share / 'incoming'
        self.datasets = self.share / 'datasets' / 'managed'
        self.models = self.share / 'models' / 'managed'
        for path in (self.incoming, self.datasets, self.models):
            path.mkdir(parents=True)
        self.username = ing.pwd.getpwuid(os.getuid()).pw_name
        self.bucket = self.incoming / self.username
        self.bucket.mkdir(mode=0o750)
        self.db = self.root / 'private-state' / 'state.sqlite3'
        self.policy = ing.Policy(state_db=self.db, incoming=self.incoming, datasets=self.datasets, models=self.models,
                                 share=self.share, coordinator_uid=os.getuid(), check_mounts=False,
                                 coordinator_host=socket.gethostname(),
                                 max_bytes=1024 * 1024, max_files=100, max_entries=200)
        self.document = {'schema_version': '2.0', 'type': 'dataset', 'title': '可复现语音样例',
                         'summary': '合成测试资料，非真人记录', 'source': {'description': '本测试生成'},
                         'rights': {'team_use': 'allowed', 'external_distribution': 'prohibited'},
                         'contributor': {'name': 'Self-reported name'}}

    def submission(self, sid='submission-1', prepare=True, document=None):
        directory = self.bucket / sid
        directory.mkdir(mode=0o750)
        (directory / 'payload' / 'empty').mkdir(parents=True)
        (directory / 'payload' / 'data.txt').write_bytes('hello 语料'.encode('utf-8'))
        (directory / 'submission.json').write_bytes(ing.encode(document or self.document))
        if prepare:
            ing.prepare(directory, self.policy)
        return directory

    def coordinator(self):
        return ing.Coordinator(self.db, self.policy)

    def approve(self, worker, directory, resource='speech', version='v1'):
        worker.scan()
        jid = self.username + '/' + directory.name
        job = worker.verify(jid)
        return worker.approve(jid, job['content_digest'], 'dataset', resource, version)

    def test_end_to_end_requires_approval_retains_source_and_emits_outbox(self):
        directory = self.submission()
        with self.coordinator() as worker:
            worker.scan()
            jid = self.username + '/submission-1'
            with self.assertRaisesRegex(ing.IngestionError, 'requires_digest_bound'):
                worker.publish(jid)
            job = self.approve(worker, directory)
            finished = worker.publish(job['id'])
            self.assertEqual(finished['status'], 'published')
        target = self.datasets / 'speech' / 'v1'
        self.assertTrue((target / 'READY.json').exists())
        self.assertTrue((target / 'payload' / 'empty').is_dir())
        self.assertEqual((target / 'payload' / 'data.txt').read_bytes(), (directory / 'payload' / 'data.txt').read_bytes())
        self.assertNotEqual((target / 'payload' / 'data.txt').stat().st_ino, (directory / 'payload' / 'data.txt').stat().st_ino)
        self.assertTrue((directory / 'READY.json').exists())
        assets = ing.published_assets(self.db)
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]['curation_status'], 'team_card_pending')
        self.assertEqual(assets[0]['rights']['external_distribution'], 'prohibited')
        self.assertEqual(assets[0]['source_identity']['source_directory_uid'], os.getuid())
        self.assertEqual(ing.published_assets(self.db, limit=1), assets)
        with self.assertRaisesRegex(ing.IngestionError, 'published_limit_invalid'):
            ing.published_assets(self.db, limit=0)

    def test_snapshot_is_readonly_missing_is_not_created_and_modes_are_honest(self):
        before = set(self.root.iterdir())
        self.assertEqual(ing.snapshot(self.db)['mode'], 'not-configured')
        self.assertEqual(set(self.root.iterdir()), before)
        with self.coordinator() as worker:
            self.assertEqual(ing.snapshot(self.db)['mode'], 'planned')
            worker.scan()
            self.assertEqual(ing.snapshot(self.db)['mode'], 'active')
            worker.set_meta('last_heartbeat_at', '2000-01-01T00:00:00+00:00')
            worker.connection.commit()
            self.assertEqual(ing.snapshot(self.db)['mode'], 'worker-stale')
            worker.set_meta('worker_enabled', False)
            worker.connection.commit()
            self.assertEqual(ing.snapshot(self.db)['mode'], 'disabled')
            with self.assertRaisesRegex(ing.IngestionError, 'worker_disabled'):
                worker.scan()
        readonly = ing.readonly_db(self.db)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                readonly.execute("INSERT INTO meta VALUES ('forbidden','true')")
        finally:
            readonly.close()

    def test_prepare_never_overwrites_a_submission(self):
        directory = self.submission()
        ready = (directory / 'READY.json').read_bytes()
        with self.assertRaisesRegex(ing.IngestionError, 'not_overwritten'):
            ing.prepare(directory, self.policy)
        self.assertEqual((directory / 'READY.json').read_bytes(), ready)
        self.assertEqual(stat.S_IMODE((directory / 'READY.json').stat().st_mode), 0o640)

    def test_crash_before_ready_is_not_scanned_or_overwritten(self):
        directory = self.submission(prepare=False)
        real_create = ing.create_once
        def crash(path, *args):
            if path.name == 'READY.json':
                raise OSError('fixture before ready')
            return real_create(path, *args)
        with mock.patch.object(ing, 'create_once', side_effect=crash):
            with self.assertRaises(OSError):
                ing.prepare(directory, self.policy)
        self.assertTrue((directory / 'manifest.jsonl').exists())
        self.assertFalse((directory / 'READY.json').exists())
        with self.coordinator() as worker:
            self.assertEqual(worker.scan(), [])
        with self.assertRaisesRegex(ing.IngestionError, 'not_overwritten'):
            ing.prepare(directory, self.policy)

    def test_external_symlink_hardlink_fifo_and_private_source_are_rejected(self):
        outside = self.root / 'private-data'
        outside.write_bytes(b'private sentinel')
        for kind in ('symlink', 'hardlink', 'fifo'):
            with self.subTest(kind=kind):
                directory = self.submission(kind, prepare=False)
                entry = directory / 'payload' / 'unsafe'
                if kind == 'symlink':
                    entry.symlink_to(outside)
                elif kind == 'hardlink':
                    os.link(outside, entry)
                else:
                    os.mkfifo(entry)
                with self.assertRaises(ing.IngestionError):
                    ing.prepare(directory, self.policy)
                self.assertFalse((directory / 'READY.json').exists())
        with self.assertRaisesRegex(ing.IngestionError, 'outside_incoming'):
            ing.prepare(self.root, self.policy)

    def test_anchored_open_rejects_replaced_parent_symlink(self):
        safe = self.root / 'safe'
        safe.mkdir()
        private = self.root / 'private'
        private.mkdir()
        (private / 'file').write_bytes(b'must not read')
        safe.rmdir(); safe.symlink_to(private, target_is_directory=True)
        with self.assertRaises(OSError):
            ing.open_absolute(safe / 'file', os.O_RDONLY)

    def test_ready_tampering_and_missing_extra_payload_fail_verification(self):
        for mutation in ('hash', 'missing', 'extra', 'content'):
            with self.subTest(mutation=mutation):
                directory = self.submission(mutation)
                with self.coordinator() as worker:
                    worker.scan()
                    if mutation == 'hash':
                        (directory / 'submission.json').write_bytes(ing.encode({**self.document, 'title': 'Changed'}))
                    elif mutation == 'missing':
                        (directory / 'payload' / 'data.txt').unlink()
                    elif mutation == 'extra':
                        (directory / 'payload' / 'new.txt').write_bytes(b'new')
                    else:
                        (directory / 'payload' / 'data.txt').write_bytes(b'changed')
                    result = worker.verify(self.username + '/' + mutation)
                    self.assertEqual(result['status'], 'failed')

    def test_unknown_rights_and_large_submissions_cannot_be_approved(self):
        doc = copy.deepcopy(self.document)
        doc['rights']['team_use'] = 'unknown'
        unknown = self.submission('unknown', document=doc)
        big = self.submission('oversized')
        with self.coordinator() as worker:
            worker.scan()
            job = worker.verify(self.username + '/' + unknown.name)
            self.assertEqual(job['status'], 'needs_information')
            with self.assertRaisesRegex(ing.IngestionError, 'not_eligible'):
                worker.approve(job['id'], job['content_digest'], 'dataset', 'unknown', 'v1')
        small = dataclasses.replace(self.policy, max_bytes=1)
        with ing.Coordinator(self.db, small) as worker:
            job = worker.verify(self.username + '/' + big.name)
            self.assertEqual(job['status'], 'review_required')
            self.assertTrue(job['reason_code'].startswith('manual_review_'))
            with self.assertRaisesRegex(ing.IngestionError, 'not_eligible'):
                worker.approve(job['id'], job['content_digest'], 'dataset', 'big', 'v1')

    def test_one_coordinator_and_one_target_reservation(self):
        one, two = self.submission('one'), self.submission('two')
        with self.coordinator() as worker:
            with self.assertRaisesRegex(ing.IngestionError, 'already_running'):
                with self.coordinator():
                    pass
            self.approve(worker, one)
            with self.assertRaisesRegex(ing.IngestionError, 'reserved_by_other'):
                self.approve(worker, two)

    def test_bad_digest_and_namespace_cannot_authorize_publication(self):
        directory = self.submission()
        with self.coordinator() as worker:
            worker.scan()
            job = worker.verify(self.username + '/' + directory.name)
            with self.assertRaisesRegex(ing.IngestionError, 'approval_digest_mismatch'):
                worker.approve(job['id'], '0' * 64, 'dataset', 'safe', 'v1')
            for value in ('../legacy', '/data/models', 'a/b'):
                with self.assertRaisesRegex(ing.IngestionError, 'invalid_identifier'):
                    worker.plan(job['id'], 'dataset', value, 'v1')
            with self.assertRaisesRegex(ing.IngestionError, 'target_kind'):
                worker.plan(job['id'], 'model', 'safe', 'v1')

    def test_existing_nonempty_target_is_never_overwritten(self):
        directory = self.submission()
        with self.coordinator() as worker:
            job = self.approve(worker, directory)
            target = self.datasets / 'speech' / 'v1'
            target.mkdir(parents=True)
            (target / 'sentinel').write_bytes(b'other resource')
            with self.assertRaises(FileExistsError):
                worker.publish(job['id'])
            self.assertEqual((target / 'sentinel').read_bytes(), b'other resource')
            self.assertFalse((target / 'READY.json').exists())

    def test_open_source_writer_after_approval_revokes_ready(self):
        directory = self.submission()
        with self.coordinator() as worker:
            job = self.approve(worker, directory)
            with (directory / 'payload' / 'data.txt').open('r+b') as writer:
                writer.write(b'WRITER'); writer.flush(); os.fsync(writer.fileno())
            with self.assertRaisesRegex(ing.IngestionError, 'manifest_mismatch'):
                worker.publish(job['id'])
            self.assertEqual(worker.job(job['id'])['status'], 'failed')
            self.assertIsNone(worker.job(job['id'])['approval'])
            self.assertFalse((self.datasets / 'speech').exists())

    def test_crash_during_copy_retains_incomplete_version_and_requires_new_version(self):
        directory = self.submission()
        with self.coordinator() as worker:
            job = self.approve(worker, directory)
            with mock.patch.object(worker, 'copy_payload', side_effect=OSError('fixture interrupted copy')):
                with self.assertRaises(OSError):
                    worker.publish(job['id'])
            target = self.datasets / 'speech' / 'v1'
            inode = target.stat().st_ino
            self.assertFalse((target / 'READY.json').exists())
            result = worker.publish(job['id'])
            self.assertEqual(result['status'], 'review_required')
            self.assertEqual(target.stat().st_ino, inode)
            with self.assertRaisesRegex(ing.IngestionError, 'already_exists'):
                worker.approve(job['id'], job['content_digest'], 'dataset', 'speech', 'v1')
            new = worker.approve(job['id'], job['content_digest'], 'dataset', 'speech', 'v2')
            self.assertEqual(worker.publish(new['id'])['status'], 'published')
            self.assertTrue(target.exists())

    def test_crash_after_ready_recovers_by_verifying_destination_without_copy(self):
        directory = self.submission()
        with self.coordinator() as worker:
            job = self.approve(worker, directory)
            with mock.patch.object(worker, 'finalize', side_effect=OSError('fixture db unavailable')):
                with self.assertRaises(OSError):
                    worker.publish(job['id'])
            self.assertEqual(worker.job(job['id'])['status'], 'publishing')
            with mock.patch.object(worker, 'copy_payload', side_effect=AssertionError('must not copy twice')):
                self.assertEqual(worker.publish(job['id'])['status'], 'published')
                self.assertEqual(worker.publish(job['id'])['status'], 'published')
            self.assertEqual(len(ing.published_assets(self.db)), 1)

    def test_published_payload_tamper_is_not_silently_recovered(self):
        directory = self.submission()
        with self.coordinator() as worker:
            job = self.approve(worker, directory)
            worker.publish(job['id'])
            (self.datasets / 'speech' / 'v1' / 'payload' / 'data.txt').write_bytes(b'tampered')
            with self.assertRaisesRegex(ing.IngestionError, 'published_payload_changed'):
                worker.publish(job['id'])

    def test_state_root_mount_and_namespace_guards_fail_closed(self):
        shared_db = self.share / 'state' / 'state.sqlite3'
        with self.assertRaisesRegex(ing.IngestionError, 'outside_shared'):
            with ing.Coordinator(shared_db, dataclasses.replace(self.policy, state_db=shared_db)):
                pass
        guarded = dataclasses.replace(self.policy, check_mounts=True)
        with mock.patch.object(ing, 'mount', return_value={'target': '/data/share', 'source': 'wrong', 'fstype': 'nfs'}):
            with self.assertRaisesRegex(ing.IngestionError, 'unexpected_shared_mount'):
                ing.shared_guard(guarded, [self.incoming])
            with self.assertRaisesRegex(ing.IngestionError, 'local_persistent'):
                with ing.Coordinator(self.db, guarded):
                    pass
        with mock.patch.object(ing.os, 'getuid', return_value=0), mock.patch.object(ing.os, 'geteuid', return_value=0):
            with self.assertRaisesRegex(ing.IngestionError, 'coordinator_uid'):
                with self.coordinator():
                    pass

    def test_json_ambiguity_is_rejected_and_optional_unknowns_remain_unknown(self):
        for raw in ('{"title":"one","title":"two"}', '{"value":NaN}', '{"value":Infinity}'):
            with self.assertRaisesRegex(ing.IngestionError, 'json_'):
                ing.decode(raw)
        document = copy.deepcopy(self.document)
        document['source']['reference'] = None
        document['rights']['basis'] = None
        document['rights']['license_id'] = None
        document['contributor']['contact'] = None
        self.assertEqual(ing.validate_submission(document), document)
        directory = self.submission('null-options', document=document)
        self.assertIsNone(ing.read_submission(directory, self.policy)['submission']['source']['reference'])

    def test_other_host_cannot_create_a_second_coordinator_database(self):
        other = dataclasses.replace(self.policy, coordinator_host='another-host')
        with self.assertRaisesRegex(ing.IngestionError, 'host_not_authorized'):
            with ing.Coordinator(self.db, other):
                pass
        self.assertFalse(self.db.parent.exists())

    def test_alternate_local_database_cannot_bypass_single_coordinator_policy(self):
        other = self.root / 'other-state' / 'queue.sqlite3'
        with self.assertRaisesRegex(ing.IngestionError, 'database_not_authorized'):
            with ing.Coordinator(other, self.policy):
                pass
        self.assertFalse(other.parent.exists())


if __name__ == '__main__':
    unittest.main()
