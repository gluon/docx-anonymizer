"""The packaged executable's entry point.

PyInstaller runs its entry script as ``__main__`` with no package
around it. ``src/dxanon/__main__.py`` was given to it directly, and
every relative import in that file fails that way, so the executable
could never start: not for the self-check, and not for the user either.

Nothing caught it, because every other way of running the program goes
through the package. ``python -m dxanon`` builds it, the tests import
it. Only the build did not, and the build was the one path nobody had
ever run.

The failure was also silent: a ``--windowed`` build reports a fatal
startup error in a message box, so the process sat waiting for a click
and the CI step hung for eighteen minutes before being cancelled.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "anonymiseur.py"
SRC = ROOT / "src"


class TheEntryPoint(unittest.TestCase):
    def test_it_exists_where_the_build_expects_it(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn(ENTRY.name, workflow, "the build points somewhere else")
        self.assertTrue(ENTRY.exists())

    def test_it_runs_as_a_plain_script(self):
        """Exactly how PyInstaller runs it: a file, not a module."""
        result = _run([str(ENTRY), "--self-check"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK", result.stdout)

    def test_the_package_entry_point_still_works(self):
        """What the developer uses, which must not break either."""
        result = _run(["-m", "dxanon", "--self-check"])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_module_cannot_be_the_entry_script(self):
        """The defect itself, pinned.

        Pointing the build back at src/dxanon/__main__.py must fail
        here rather than in a message box on a user's machine.
        """
        result = _run([str(SRC / "dxanon" / "__main__.py"), "--self-check"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("relative import", result.stderr)


def _run(arguments: list[str]) -> subprocess.CompletedProcess:
    import os

    environment = dict(os.environ, PYTHONPATH=str(SRC))
    return subprocess.run(
        [sys.executable, *arguments],
        capture_output=True, text=True, timeout=120, env=environment, cwd=str(ROOT),
    )


if __name__ == "__main__":
    unittest.main()
