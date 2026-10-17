"""Names the file carries without ever printing them.

The grid was built from the text of the story parts alone, so a
reviewer named only in a ``w:author`` attribute never entered the table,
was never replaced, and was not looked for by the refusal check, which
only searches for what the table holds. The export went out with the
name in it and nothing reported a thing.

The existing round-trip tests passed because they built the table by
hand. These go through the path the window actually uses.
"""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures  # noqa: E402
from dxanon import engine, source, workflow  # noqa: E402
from dxanon.package import Package  # noqa: E402

#: Planted in the fixture's metadata and nowhere in its body.
METADATA_ONLY = ("Jean Dupont", "Sylvie Marchand")


class ReadingADocument(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.source = fixtures.build(self.dir / "Dupont_conclusions_v3.docx")
        self.text, self.images, self.identities = source.read_document(self.source)

    def test_those_names_really_are_absent_from_the_body(self):
        """Otherwise the tests below would pass for the wrong reason."""
        for name in METADATA_ONLY:
            self.assertNotIn(name, self.text, name)

    def test_they_are_found_anyway(self):
        for name in METADATA_ONLY:
            self.assertIn(name, self.identities, name)

    def test_initials_are_found_too(self):
        self.assertIn("SM", self.identities)

    def test_the_file_name_is_read(self):
        """Often the most talkative part of a document."""
        self.assertIn("Dupont", self.identities)


class TheWindowsPath(unittest.TestCase):
    """Exactly what the window does: read, build the grid, export."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.source = fixtures.build(self.dir / "Dupont_conclusions_v3.docx")
        text, images, identities = source.read_document(self.source)
        self.grid = workflow.build(text, images=images, known=identities)
        self.destination = self.dir / "anon.docx"
        engine.anonymize(self.source, self.destination, self.grid.to_mapping())

    def test_nothing_leaks_anywhere_in_the_package(self):
        package = Package.open(self.destination)
        for part in package.parts:
            if not part.name.endswith((".xml", ".rels")):
                continue
            content = part.data.decode("utf-8", errors="replace")
            for name in METADATA_ONLY:
                self.assertNotIn(name, content, f"{name} survives in {part.name}")

    def test_the_authors_were_actually_rewritten(self):
        """Not simply absent: replaced by something."""
        package = Package.open(self.destination)
        document = package.get("word/document.xml").data.decode()
        comments = package.get("word/comments.xml").data.decode()

        self.assertTrue(re.search(r'w:author="[^"]+"', document))
        self.assertTrue(re.search(r'w:author="[^"]+" w:initials="[^"]+"', comments))

    def test_a_metadata_name_is_offered_as_certain(self):
        rows = {row.value: row for row in self.grid.rows}
        for name in METADATA_ONLY:
            self.assertIn(name, rows, name)
            self.assertEqual(rows[name].kind, "author")
            self.assertEqual(rows[name].occurrences, 0)


if __name__ == "__main__":
    unittest.main()
