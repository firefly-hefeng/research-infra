import base64
import hashlib
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

from tools import install_monitor_access as install
from tools import setup_server_monitor as setup
from tools.collect_server_resources import REMOTE_PROBE


def key(byte):
    raw = struct.pack('>I', 11) + b'ssh-ed25519' + struct.pack('>I', 32) + bytes([byte]) * 32
    return 'ssh-ed25519 ' + base64.b64encode(raw).decode()


class MonitorAccessTests(unittest.TestCase):
    def test_restricted_line_preserves_all_existing_lines_and_is_idempotent(self):
        previous = ('# administrator keys\n' + key(1) + ' retained\n').encode()
        updated, changed = install.append_restricted(previous, key(2) + ' ignored comment')
        self.assertTrue(changed)
        self.assertTrue(updated.startswith(previous))
        self.assertEqual(updated.count(b'rdc-readonly-monitor'), 1)
        self.assertIn(('restrict,command="' + install.FORCED_COMMAND + '"').encode(), updated)
        self.assertEqual(install.append_restricted(updated, key(2)), (updated, False))

    def test_existing_general_key_is_never_relabelled_as_restricted(self):
        for existing in (key(2), 'command="/bin/sh" ' + key(2)):
            with self.assertRaisesRegex(ValueError, 'different_restrictions'):
                install.append_restricted((existing + '\n').encode(), key(2))

    def test_invalid_public_keys_and_option_injection_are_rejected(self):
        for value in ('ssh-rsa AAAA', 'restrict ' + key(1), 'ssh-ed25519 bad!', 'ssh-ed25519 AAAA', ''):
            with self.assertRaises(ValueError):
                install.public_key(value)
        line = install.authorized_line(key(1) + '\ncommand="/bin/sh"')
        self.assertEqual(line.count('command='), 1)
        self.assertNotIn('\n', line)

    def test_fixed_probe_bytes_match_collector_and_ignore_original_command(self):
        self.assertEqual(install.REMOTE_PROBE, REMOTE_PROBE)
        self.assertNotIn('SSH_ORIGINAL_COMMAND', REMOTE_PROBE)
        self.assertNotIn('query-compute-apps', REMOTE_PROBE)
        self.assertNotIn('/data/users', REMOTE_PROBE)
        compile(REMOTE_PROBE, '<fixed-system-probe>', 'exec')

    def test_timer_and_service_only_touch_monitor_snapshot_and_private_key(self):
        units = setup.units()
        self.assertEqual(set(units), {'research-server-monitor.service', 'research-server-monitor.timer'})
        service = units['research-server-monitor.service']
        self.assertIn('User=rmp', service)
        self.assertIn('NoNewPrivileges=true', service)
        self.assertIn('--timeout 20', service)
        self.assertIn('TimeoutStartSec=35', service)
        self.assertIn('OnUnitInactiveSec=60', units['research-server-monitor.timer'])
        self.assertNotIn('password', service)
        self.assertNotIn('research-data-center.service', units['research-server-monitor.timer'])

    @unittest.skipUnless(sys.platform.startswith('linux'), 'File ownership/dirfd check requires Linux')
    def test_atomic_install_does_not_follow_target_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / 'original'
            original.write_bytes(b'preserve')
            target = root / 'authorized_keys'
            target.symlink_to(original)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                install.atomic(target, b'forbidden', os.getuid(), os.getgid(), 0o600)
            self.assertEqual(original.read_bytes(), b'preserve')


if __name__ == '__main__':
    unittest.main()
