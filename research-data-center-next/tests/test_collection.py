"""Linux-only tests for privileged configuration-content read boundaries."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


@unittest.skipUnless(sys.platform.startswith("linux") and Path("/proc/self/fd").is_dir(),
                     "Collector content-read guards require Linux /proc and O_NOFOLLOW")
class ConfigurationBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        module_path = Path(__file__).resolve().parents[1] / "tools" / "collect_metadata.py"
        spec = importlib.util.spec_from_file_location("rdc_collect_metadata_tests", module_path)
        cls.collector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.collector)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.allowed = self.root / "approved-models"
        self.allowed.mkdir()
        self.allowed_roots = [self.allowed.resolve()]

    def test_regular_config_in_approved_root_is_read(self):
        config = self.allowed / "config.json"
        config.write_text(json.dumps({"model_type": "test", "architectures": ["TestModel"]}), encoding="utf-8")
        self.assertEqual(self.collector.read_config(config, self.allowed_roots),
                         {"model_type": "test", "architectures": ["TestModel"]})

    def test_symlink_within_approved_root_is_read(self):
        blob = self.allowed / "config-blob"
        blob.write_text('{"model_type":"safe-cache-link"}', encoding="utf-8")
        config = self.allowed / "config.json"
        config.symlink_to(blob)
        self.assertEqual(self.collector.read_config(config, self.allowed_roots), {"model_type": "safe-cache-link"})

    def test_symlink_outside_approved_root_is_rejected_before_open(self):
        outside = self.root / "private.json"
        outside.write_text('{"model_type":"private-content"}', encoding="utf-8")
        config = self.allowed / "config.json"
        config.symlink_to(outside)
        original_open = os.open
        with mock.patch.object(self.collector.os, "open", wraps=original_open) as opened:
            with self.assertRaisesRegex(ValueError, "outside_approved_model_roots"):
                self.collector.read_config(config, self.allowed_roots)
            opened.assert_not_called()

    def test_oversized_config_is_rejected_before_content_read(self):
        config = self.allowed / "config.json"
        config.write_bytes(b" " * 200001)
        original_read = os.read
        with mock.patch.object(self.collector.os, "read", wraps=original_read) as reader:
            with self.assertRaisesRegex(ValueError, "type_or_size_rejected"):
                self.collector.read_config(config, self.allowed_roots)
            reader.assert_not_called()

    def test_directory_is_rejected_before_content_read(self):
        config = self.allowed / "config.json"
        config.mkdir()
        original_read = os.read
        with mock.patch.object(self.collector.os, "read", wraps=original_read) as reader:
            with self.assertRaisesRegex(ValueError, "type_or_size_rejected"):
                self.collector.read_config(config, self.allowed_roots)
            reader.assert_not_called()

    def test_fifo_is_rejected_without_blocking_or_reading(self):
        config = self.allowed / "config.json"
        os.mkfifo(config)
        original_read = os.read
        with mock.patch.object(self.collector.os, "read", wraps=original_read) as reader:
            with self.assertRaisesRegex(ValueError, "type_or_size_rejected"):
                self.collector.read_config(config, self.allowed_roots)
            reader.assert_not_called()

    def test_non_object_config_is_rejected(self):
        config = self.allowed / "config.json"
        config.write_text('[]', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'configuration_not_object'):
            self.collector.read_config(config, self.allowed_roots)

    def test_external_collection_configuration_is_rejected_before_stat(self):
        with mock.patch.object(self.collector, 'check') as checker:
            with self.assertRaisesRegex(ValueError, 'outside_public_roots'):
                self.collector.collect({'paths':['/outside-test/root'], 'model_roots':['/data/models']})
            checker.assert_not_called()

    def test_public_entry_with_external_symlink_does_not_stat_target(self):
        outside = self.root / 'outside'
        outside.mkdir()
        link = self.allowed / 'external'
        link.symlink_to(outside, target_is_directory=True)
        with mock.patch.object(self.collector, 'PUBLIC_ROOTS', self.allowed_roots):
            result = self.collector.check(str(link))
        self.assertEqual(result['reason'], 'outside_public_roots')
        self.assertNotIn('realpath', result)

    def test_external_model_root_link_is_rejected_before_configuration_read(self):
        outside = self.root / 'external-model-root'
        outside.mkdir()
        link = self.allowed / 'linked-root'
        link.symlink_to(outside, target_is_directory=True)
        with mock.patch.object(self.collector, 'PUBLIC_ROOTS', self.allowed_roots):
            with mock.patch.object(self.collector, 'check') as checker:
                with self.assertRaisesRegex(ValueError, 'model_root_target_outside_public_roots'):
                    self.collector.collect({'paths':[], 'model_roots':[str(link)]})
                checker.assert_not_called()

    def test_destination_mode_rejects_wrong_mount_before_any_collection(self):
        config = {'paths': ['/data/datasets/example'], 'model_roots': ['/data/models'],
                  'location_mode': 'destination_verification'}
        with mock.patch.object(self.collector, 'mount_info', return_value={
                'target': '/data', 'source': '/dev/local', 'fstype': 'xfs'}):
            with mock.patch.object(self.collector, '_collect') as collected:
                with self.assertRaisesRegex(ValueError, 'mount_receipt'):
                    self.collector.collect(config)
                collected.assert_not_called()

    def test_destination_mode_maps_exact_roots_then_restores_default_scope(self):
        config = {'paths': ['/data/datasets/example'], 'model_roots': ['/data/models'],
                  'location_mode': 'destination_verification'}
        previous = list(self.collector.PUBLIC_ROOTS)
        with mock.patch.object(self.collector, 'mount_info', return_value={
                'target': '/data/share', 'source': '10.0.0.202:/share', 'fstype': 'nfs'}):
            def inspect(prepared):
                self.assertEqual(prepared['paths'], ['/data/share/datasets/example'])
                self.assertEqual(prepared['model_roots'], ['/data/share/models'])
                self.assertFalse(self.collector.in_scope('/data/share/public'))
                self.assertFalse(self.collector.in_scope('/data/datasets'))
                self.assertFalse(self.collector.in_scope('/data/share/datasets/../models'))
                raise RuntimeError('fixture_stop_before_scan')
            with mock.patch.object(self.collector, '_collect', side_effect=inspect):
                with self.assertRaisesRegex(RuntimeError, 'fixture_stop'):
                    self.collector.collect(config)
        self.assertEqual(self.collector.PUBLIC_ROOTS, previous)

    def test_failed_destination_mapping_restores_legacy_scope(self):
        previous = list(self.collector.PUBLIC_ROOTS)
        config = {'paths': ['/data/users/never-read'], 'model_roots': ['/data/models'],
                  'location_mode': 'destination_verification'}
        with mock.patch.object(self.collector, 'mount_info', return_value={
                'target': '/data/share', 'source': '10.0.0.202:/share', 'fstype': 'nfs'}):
            with mock.patch.object(self.collector, '_collect') as collected:
                with self.assertRaisesRegex(ValueError, 'outside_approved_library_roots'):
                    self.collector.collect(config)
                collected.assert_not_called()
        self.assertEqual(self.collector.PUBLIC_ROOTS, previous)

    def test_shared_mode_preserves_canonical_paths_and_checks_both_mounts(self):
        config = {'paths': ['/data/share/datasets/example'], 'model_roots': ['/data/share/models'],
                  'location_mode': 'shared'}
        previous = list(self.collector.PUBLIC_ROOTS)
        def inspect(prepared):
            self.assertEqual(prepared, config)
            self.assertEqual([str(path) for path in self.collector.PUBLIC_ROOTS],
                             ['/data/share/datasets', '/data/share/models'])
            self.assertFalse(self.collector.in_scope('/data/share/public'))
            self.assertFalse(self.collector.in_scope('/data/models'))
            return {'fixture': True}
        with mock.patch.object(self.collector, 'mount_info', return_value={
                'target': '/data/share', 'source': '10.0.0.202:/share', 'fstype': 'nfs'}) as mounts:
            with mock.patch.object(self.collector, 'destination_path', side_effect=AssertionError('must not remap')):
                with mock.patch.object(self.collector, '_collect', side_effect=inspect):
                    result = self.collector.collect(config)
        self.assertEqual(result, {'fixture': True, 'location_mode': 'shared'})
        self.assertEqual([call.args[0] for call in mounts.call_args_list],
                         ['/data/share', '/data/share/datasets', '/data/share/models'])
        self.assertEqual(self.collector.PUBLIC_ROOTS, previous)

    def test_shared_mode_rejects_old_external_and_noncanonical_configuration(self):
        invalid = ['/data/datasets/example', '/data/models', '/data/share/public',
                   '/data/share/datasets-other', '/data/share/datasets/../users',
                   '/data/share/datasets//example', 'relative/path', None]
        for path in invalid:
            with self.subTest(path=path):
                with mock.patch.object(self.collector, 'mount_info') as mounts:
                    with mock.patch.object(self.collector, '_collect') as collected:
                        with self.assertRaisesRegex(ValueError, 'requires_canonical'):
                            self.collector.collect({'paths': [path], 'model_roots': ['/data/share/models'],
                                                    'location_mode': 'shared'})
                        mounts.assert_not_called()
                        collected.assert_not_called()
        with mock.patch.object(self.collector, '_collect') as collected:
            with self.assertRaisesRegex(ValueError, 'requires_canonical'):
                self.collector.collect({'paths': [], 'model_roots': ['/data/share/datasets'],
                                        'location_mode': 'shared'})
            collected.assert_not_called()

    def test_shared_mode_rejects_nested_mount_or_root_alias_before_collection(self):
        config = {'paths': [], 'model_roots': ['/data/share/models'], 'location_mode': 'shared'}
        previous = list(self.collector.PUBLIC_ROOTS)
        valid = {'target': '/data/share', 'source': '10.0.0.202:/share', 'fstype': 'nfs'}
        wrong = {'target': '/data/share/datasets', 'source': '/dev/local', 'fstype': 'xfs'}
        with mock.patch.object(self.collector, 'mount_info', side_effect=[valid, wrong]):
            with mock.patch.object(self.collector, '_collect') as collected:
                with self.assertRaisesRegex(ValueError, 'mount_receipt'):
                    self.collector.collect(config)
                collected.assert_not_called()
        self.assertEqual(self.collector.PUBLIC_ROOTS, previous)
        with mock.patch.object(self.collector, 'mount_info', return_value=valid):
            with mock.patch.object(self.collector.os.path, 'realpath', return_value='/data/share/public'):
                with mock.patch.object(self.collector, '_collect') as collected:
                    with self.assertRaisesRegex(ValueError, 'root_must_be_canonical'):
                        self.collector.collect(config)
                    collected.assert_not_called()
        self.assertEqual(self.collector.PUBLIC_ROOTS, previous)


if __name__ == "__main__":
    unittest.main()
