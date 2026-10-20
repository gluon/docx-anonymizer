"""The self-check, including the case where there is nowhere to print."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dxanon import __main__ as entry  # noqa: E402
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


class TheReport(unittest.TestCase):
    """The report has to reach a machine with no console.

    A --windowed build has no standard output to redirect, so the shell
    redirection the Windows job used produced an empty file, and the
    check that read it concluded the bundle had no recognition engine
    when the question had never been asked.
    """

    def test_the_report_is_written_where_it_is_asked_for(self):
        import tempfile

        path = Path(tempfile.mkdtemp()) / "rapport.txt"
        out, err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = None  # as in the packaged build
        try:
            code = entry.main(["--self-check", "--report", str(path)])
        finally:
            sys.stdout, sys.stderr = out, err
        self.assertEqual(code, 0)
        self.assertIn("OK :", path.read_text(encoding="utf-8"))

    def test_without_the_option_nothing_is_written(self):
        self.assertIsNone(entry._report_path(["--self-check"]))
        self.assertEqual(entry._report_path(["--report", "a.txt"]), "a.txt")
        self.assertIsNone(entry._report_path(["--self-check", "--report"]))


if __name__ == "__main__":
    unittest.main()
