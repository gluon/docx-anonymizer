"""The self-check, including the case where there is nowhere to print."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dxanon.__main__ import self_check  # noqa: E402


class SelfCheck(unittest.TestCase):
    def test_it_passes(self):
        self.assertEqual(self_check(), 0)

    def test_it_survives_having_no_console(self):
        """A PyInstaller --windowed build has no stdout at all.

        sys.stdout is None there, a bare print raises AttributeError, and
        the check would fail for the one reason it is not meant to test,
        reporting a broken bundle that is in fact fine.
        """
        out, err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = None
        try:
            code = self_check()
        finally:
            sys.stdout, sys.stderr = out, err
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
