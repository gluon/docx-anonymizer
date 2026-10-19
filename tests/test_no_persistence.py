"""Nothing is written anywhere unless the user asked for a file.

The correspondence table maps every pseudonym back to the client. Put it
on the firm's disk and it becomes the most dangerous file in the case
folder, outliving the work that needed it. So the tool is one-shot: the
table exists in memory for the length of the round trip and nowhere
else.

These tests enforce that by watching the filesystem rather than by
reading the code, because the failure mode is a library writing a cache
or a log nobody meant to add.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures  # noqa: E402
from dxanon import plaintext, workflow  # noqa: E402
from dxanon.engine import anonymize, deanonymize  # noqa: E402

SAMPLE = Path(__file__).resolve().parent / "sample_mail.txt"


class NothingIsWritten(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.before = _snapshot(self.home)
        self._real_home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)

    def tearDown(self):
        if self._real_home is not None:
            os.environ["HOME"] = self._real_home

    def test_a_full_text_cycle_touches_no_file(self):
        text = SAMPLE.read_text(encoding="utf-8")
        grid = workflow.build(text)
        mapping = grid.to_mapping()
        masked = plaintext.anonymize(text, mapping)
        restored, _ = plaintext.deanonymize(masked, mapping)

        self.assertEqual(restored, text)
        self.assertEqual(_snapshot(self.home), self.before, "something was written")

    def test_building_a_grid_writes_nothing(self):
        workflow.build(SAMPLE.read_text(encoding="utf-8"))
        self.assertEqual(_snapshot(self.home), self.before)

    def test_a_file_cycle_writes_only_what_was_asked_for(self):
        source = fixtures.build(self.home / "piece.docx")
        anon = self.home / "piece_ANON.docx"
        final = self.home / "piece_FINAL.docx"

        text, _ = _text_of(source)
        mapping = workflow.build(text).to_mapping()
        anonymize(source, anon, mapping)
        deanonymize(anon, final, mapping, require_all=False)

        written = _snapshot(self.home) - self.before
        self.assertEqual(written, {source, anon, final}, "an unexpected file appeared")

    def test_the_table_has_no_save_method_left(self):
        """Removing persistence means removing the way to persist.

        A `save` still sitting on Mapping is an invitation to call it,
        and one call puts the client's names on the disk for good.
        """
        from dxanon.mapping import Mapping

        for forbidden in ("save", "load"):
            self.assertFalse(hasattr(Mapping, forbidden), f"Mapping.{forbidden} is back")

    def test_there_is_no_session_or_lexicon_module(self):
        for module in ("dxanon.session", "dxanon.lexicon"):
            with self.assertRaises(ImportError, msg=f"{module} is back"):
                __import__(module)


def _snapshot(folder: Path) -> set[Path]:
    return {p for p in folder.rglob("*") if p.is_file()}


def _text_of(path: Path) -> tuple[str, list[str]]:
    from dxanon import textmap
    from dxanon.package import Package

    package = Package.open(path)
    chunks = [textmap.full_text(textmap.parse(p.data)) for p in package.stories()]
    return "\n".join(c for c in chunks if c), [p.name for p in package.images()]


if __name__ == "__main__":
    unittest.main()
