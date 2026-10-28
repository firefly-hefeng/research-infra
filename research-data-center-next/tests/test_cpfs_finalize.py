"""Fault checks for the one-shot continuation; no production command is run."""
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


@unittest.skipUnless(sys.platform.startswith('linux'), 'Continuation uses Linux process primitives')
class FinalizerFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
        cls.module = importlib.import_module('cpfs_finalize')

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix='rdc-finalizer-test-')
        self.addCleanup(self.scratch.cleanup)
        self.base = Path(self.scratch.name)
        (self.base / 'finalization-policy.json').write_text('{}')
        self.patches = []
        def patch(target, name, **kwargs):
            p = mock.patch.object(target, name, **kwargs)
            result = p.start()
            self.addCleanup(p.stop)
            return result
        m = self.module
        patch(m, 'BASE', new=self.base)
        patch(m, 'STATE', new=self.base / 'finalization-state.json')
        patch(m.os, 'geteuid', return_value=0)
        patch(m.os, 'uname', return_value=types.SimpleNamespace(nodename=m.HOST))
        patch(m.os, 'umask', return_value=0o077)
        patch(m, 'check_pins')
        patch(m, 'allow_receipt_reads')
        patch(m, 'wait_verified')
        patch(m, 'save')
        patch(sys, 'argv', new=['cpfs_finalize.py', '--execute'])
        self.run = patch(m, 'run')
        original = Path.lstat
        def policy_lstat(path, *args, **kwargs):
            if path == self.base / 'finalization-policy.json':
                return types.SimpleNamespace(st_mode=0o100600, st_uid=0)
            return original(path, *args, **kwargs)
        patch(Path, 'lstat', new=policy_lstat)

    def test_failed_ordinary_account_check_never_calls_cleanup(self):
        def fail_observer(command, account=None):
            if 'cpfs_observe_destination.py' in command[1]:
                raise PermissionError('entry unreadable to ordinary account')
        self.run.side_effect = fail_observer
        with self.assertRaises(PermissionError):
            self.module.main()
        commands = [call.args[0] for call in self.run.call_args_list]
        self.assertTrue(any('switch' in cmd for cmd in commands))
        self.assertFalse(any('cleanup' in cmd for cmd in commands))
        self.assertFalse(any('publish' in cmd for cmd in commands))

    def test_existing_partial_cutover_never_retries_exchange(self):
        (self.base / 'cutover-state.json').write_text(json.dumps({'phase': 'prepared'}))
        with self.assertRaisesRegex(RuntimeError, 'Pre-existing cutover journal'):
            self.module.main()
        self.run.assert_not_called()

    def test_failed_cleanup_does_not_publish_completion(self):
        def fail_cleanup(command, account=None):
            if 'cleanup' in command:
                raise OSError('simulated interrupted deletion')
        self.run.side_effect = fail_cleanup
        with self.assertRaises(OSError):
            self.module.main()
        self.assertFalse(any('publish' in call.args[0] for call in self.run.call_args_list))


if __name__ == '__main__':
    unittest.main()
