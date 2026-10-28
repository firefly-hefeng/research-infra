"""Mount-identity fixtures use temporary directories and never mount anything."""
import dataclasses
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

import ingestion as ing


class SharedMountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='rdc-mount-guard-')
        self.addCleanup(self.tmp.cleanup)
        self.share = Path(self.tmp.name) / 'share'
        self.incoming = self.share / 'incoming'
        self.datasets = self.share / 'datasets' / 'managed'
        self.models = self.share / 'models' / 'managed'
        for path in (self.incoming, self.datasets, self.models):
            path.mkdir(parents=True)
        self.policy = ing.Policy(share=self.share, incoming=self.incoming,
                                 datasets=self.datasets, models=self.models)
        self.root = {'target': str(self.share), 'source': self.policy.mount_source, 'fstype': 'nfs', 'fsroot': '/'}
        self.overlays = {}

    def managed_mount(self, prefix):
        return {'target': str(prefix), 'source': self.policy.mount_source + '/' + prefix.relative_to(self.share).as_posix(),
                'fstype': 'nfs', 'fsroot': '/'}

    def observation(self, path):
        path = Path(path)
        for prefix, value in sorted(self.overlays.items(), key=lambda item: len(str(item[0])), reverse=True):
            if path.is_relative_to(prefix):
                return value
        return self.root

    def check(self, paths):
        with mock.patch.object(ing, 'mount', side_effect=self.observation):
            ing.shared_guard(self.policy, paths)

    def test_normal_shared_mount_and_incoming_are_accepted(self):
        self.check([self.share, self.incoming, self.datasets, self.models])

    def test_exact_service_managed_mounts_and_descendants_are_accepted(self):
        for prefix in (self.datasets, self.models):
            self.overlays[prefix] = self.managed_mount(prefix)
            (prefix / 'resource' / 'v1').mkdir(parents=True)
        self.check([self.incoming, self.datasets, self.datasets / 'resource/v1', self.models / 'resource/v1'])

    def test_incoming_submount_is_not_an_allowed_exception(self):
        self.overlays[self.incoming] = self.managed_mount(self.incoming)
        with self.assertRaisesRegex(ing.IngestionError, 'unexpected_shared_mount'):
            self.check([self.incoming])

    def test_arbitrary_nested_managed_mount_is_rejected(self):
        nested = self.datasets / 'resource'
        nested.mkdir()
        self.overlays[nested] = self.managed_mount(nested)
        with self.assertRaisesRegex(ing.IngestionError, 'unexpected_shared_mount'):
            self.check([nested])

    def test_wrong_target_source_type_or_fsroot_is_rejected(self):
        changes = ({'target': str(self.datasets.parent)}, {'source': '10.0.0.203:/share/datasets/managed'},
                   {'source': self.policy.mount_source + '[/datasets/managed]'},
                   {'source': self.policy.mount_source + '/models/managed'},
                   {'fstype': 'ext4'}, {'fsroot': '/datasets/managed'}, {'fsroot': None})
        for change in changes:
            with self.subTest(change=change):
                self.overlays[self.datasets] = {**self.managed_mount(self.datasets), **change}
                with self.assertRaisesRegex(ing.IngestionError, 'unexpected_shared_mount'):
                    self.check([self.datasets])

    def test_shared_root_identity_cannot_be_replaced_by_valid_looking_submount(self):
        self.overlays[self.datasets] = self.managed_mount(self.datasets)
        original = self.root.copy()
        for change in ({'target': '/'}, {'source': '/dev/sda1'}, {'fstype': 'ext4'}, {'fsroot': '/other'}):
            with self.subTest(change=change):
                self.root = {**original, **change}
                with self.assertRaisesRegex(ing.IngestionError, 'unexpected_shared_mount'):
                    self.check([self.datasets])

    def test_managed_parent_must_still_be_on_original_root_mount(self):
        self.overlays[self.datasets] = self.managed_mount(self.datasets)
        self.overlays[self.datasets.parent] = self.managed_mount(self.datasets.parent)
        with self.assertRaisesRegex(ing.IngestionError, 'unexpected_shared_mount'):
            self.check([self.datasets])

    def test_different_device_rejected_even_with_matching_mount_strings(self):
        self.overlays[self.datasets] = self.managed_mount(self.datasets)
        original_stat = Path.stat
        def stat_fixture(path, *args, **kwargs):
            result = original_stat(path, *args, **kwargs)
            if path == self.datasets and kwargs.get('follow_symlinks', True):
                return types.SimpleNamespace(st_dev=result.st_dev + 1)
            return result
        with mock.patch.object(Path, 'stat', stat_fixture):
            with self.assertRaisesRegex(ing.IngestionError, 'unexpected_shared_mount_device'):
                self.check([self.datasets])

    def test_mount_disappears_during_guard_is_rejected(self):
        calls = 0
        def observe(path):
            nonlocal calls
            if Path(path) == self.share:
                calls += 1
                if calls > 1:
                    return {'target': '/', 'source': '/dev/sda1', 'fstype': 'ext4', 'fsroot': '/'}
            return self.observation(path)
        with mock.patch.object(ing, 'mount', side_effect=observe):
            with self.assertRaisesRegex(ing.IngestionError, 'shared_mount_changed_during_guard'):
                ing.shared_guard(self.policy, [self.incoming])

    def test_outside_path_is_rejected_even_if_mount_tool_lies(self):
        with self.assertRaisesRegex(ing.IngestionError, 'unexpected_shared_mount'):
            self.check([self.share.parent])

    def test_missing_shared_mount_is_rejected(self):
        self.root = {'target': '/', 'source': '/dev/sda1', 'fstype': 'ext4', 'fsroot': '/'}
        with self.assertRaisesRegex(ing.IngestionError, 'unexpected_shared_mount'):
            self.check([self.incoming])

    def test_mount_reader_requests_filesystem_root_and_rejects_ambiguity(self):
        response = types.SimpleNamespace(stdout=json.dumps({'filesystems': [self.root]}))
        with mock.patch.object(ing.subprocess, 'run', return_value=response) as command:
            self.assertEqual(ing.mount(self.share), self.root)
            self.assertIn('TARGET,SOURCE,FSTYPE,FSROOT', command.call_args.args[0])
        response.stdout = json.dumps({'filesystems': [self.root, self.root]})
        with mock.patch.object(ing.subprocess, 'run', return_value=response):
            with self.assertRaisesRegex(ing.IngestionError, 'mount_identity_unavailable'):
                ing.mount(self.share)


if __name__ == '__main__':
    unittest.main()
