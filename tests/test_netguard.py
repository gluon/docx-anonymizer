"""The offline claim, made checkable.

These tests patch a process-wide hook, so each one restores it.
"""

from __future__ import annotations

import socket
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dxanon.netguard import NetworkGuard  # noqa: E402


class Guard(unittest.TestCase):
    def setUp(self):
        self._connect = socket.socket.connect
        self._connect_ex = socket.socket.connect_ex
        self.guard = NetworkGuard.install()

    def tearDown(self):
        socket.socket.connect = self._connect
        socket.socket.connect_ex = self._connect_ex

    def test_a_guard_starts_clean(self):
        self.assertTrue(self.guard.clean)
        self.assertTrue(self.guard.installed)

    def test_an_outbound_connection_is_refused_and_recorded(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            with self.assertRaises(OSError):
                client.connect(("93.184.216.34", 80))

        self.assertFalse(self.guard.clean)
        self.assertIn("93.184.216.34", self.guard.attempts)

    def test_a_hostname_is_refused_without_being_resolved(self):
        """Resolution itself would already be a request leaving the machine."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            with self.assertRaises(OSError):
                client.connect(("example.com", 443))
        self.assertIn("example.com", self.guard.attempts)

    def test_connect_ex_fails_too(self):
        """The quiet variant returns an errno instead of raising."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            self.assertNotEqual(client.connect_ex(("93.184.216.34", 80)), 0)
        self.assertFalse(self.guard.clean)

    def test_loopback_is_allowed_and_does_not_raise_the_alarm(self):
        """It never leaves the machine, and toolkits use it for plumbing."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
                client.connect(("127.0.0.1", port))

        self.assertTrue(self.guard.clean)
        self.assertTrue(self.guard.loopback)

    def test_the_window_can_tell_the_two_apart(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            with self.assertRaises(OSError):
                client.connect(("8.8.8.8", 53))
        self.assertEqual(len(self.guard.attempts), 1)
        self.assertTrue(any("8.8.8.8" in a for a in self.guard.attempts))


if __name__ == "__main__":
    unittest.main()
