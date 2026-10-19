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
METADATA_ONLY = ("Jean Dupont", "Sylvie Marchand", "Paul Girard")


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

    def test_the_reviewer_list_is_read(self):
        """people.xml: w15:author, not w:author, so it was never looked at."""
        self.assertIn("Paul Girard", self.identities)

    def test_an_address_inside_a_user_id_is_read_on_its_own(self):
        self.assertIn("paul.girard@cabinet-girard.fr", self.identities)

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
        self.mapping = self.grid.to_mapping()
        engine.anonymize(self.source, self.destination, self.mapping)

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

    def test_the_reviewer_list_is_rewritten_not_dropped(self):
        people = Package.open(self.destination).get("word/people.xml").data.decode()
        self.assertNotIn("cabinet-girard", people)
        self.assertEqual(len(re.findall(r'w15:author="[^"]+"', people)), 2)
        self.assertEqual(len(re.findall(r'w15:userId="[^"]+"', people)), 2)

    def test_a_document_sent_back_untouched_is_restored(self):
        """The return trip used to demand every pseudonym in the table,
        including those the outward trip never wrote: a short form a full
        name had consumed, a word found only in the file name."""
        never = [e for e in self.mapping.entries if not self.mapping.was_used(e)]
        self.assertTrue(never, "the fixture no longer exercises the case")
        restored = self.dir / "final.docx"
        engine.deanonymize(self.destination, restored, self.mapping)
        # Text, not markup, for the story parts: a name split across runs
        # comes back in the first run, so "Jean DUP" bold + "ONT" plain
        # returns as "Jean DUPONT" all bold. A known limit of
        # textmap.apply, not what this test is about.
        from lxml import etree
        from dxanon import textmap
        canonical = lambda data: etree.tostring(etree.fromstring(data), method="c14n")
        original = Package.open(self.source)
        stories = {p.name for p in original.stories()}
        for part in Package.open(restored).parts:
            expected = original.get(part.name).data
            if part.name in stories:
                self.assertEqual(textmap.full_text(textmap.parse(part.data)),
                                 textmap.full_text(textmap.parse(expected)), part.name)
            elif part.name.endswith((".xml", ".rels")):
                self.assertEqual(canonical(part.data), canonical(expected), part.name)
            else:
                self.assertEqual(part.data, expected, part.name)

    def test_a_metadata_name_is_offered_as_certain(self):
        rows = {row.value: row for row in self.grid.rows}
        for name in METADATA_ONLY:
            self.assertIn(name, rows, name)
            self.assertEqual(rows[name].kind, "author")
            self.assertEqual(rows[name].occurrences, 0)


class NamesReadFromTheFileName(unittest.TestCase):
    """A file name is the least reliable of the three sources.

    w:author holds a person's name because Word puts one there. A file
    name holds a person's name plus dates, version numbers and office
    vocabulary, and taking all of it as certain made "Dossier" a name:
    the header of "Dossier_Benzaoui.docx" came out reading "Marc
    FORESTIER BENZAOUI".
    """

    def test_office_vocabulary_is_dropped(self):
        words = source._from_filename(Path("Dossier_Benzaoui_Confidentiel_v3.docx"), [])
        self.assertEqual(words, ["Benzaoui"])

    def test_a_plain_case_name_still_comes_through(self):
        self.assertIn("Vandenbroucke", source._from_filename(Path("Vandenbroucke.docx"), []))

    def test_the_limit_is_stated_rather_than_hidden(self):
        """A word no list knows is still offered as a name.

        That is the grid's job to catch, not this function's, and
        pretending otherwise would be the error that produced "Dossier".
        """
        words = source._from_filename(Path("Prudhommal2024_Krgzystan.docx"), [])
        self.assertTrue(words)


class TheOutputFileName(unittest.TestCase):
    def test_it_goes_through_the_table(self):
        """The refusal check reads inside the package, not its name.

        "Dossier_Benzaoui.docx" came out as "Dossier_Benzaoui_ANON.docx"
        with nothing objecting, which puts the client's name in the one
        place a reader sees before opening anything.
        """
        from dxanon.cli import _masked_name
        from dxanon.mapping import Mapping

        mapping = Mapping()
        mapping.add("Benzaoui", "Lagarde")
        masked = _masked_name(Path("Dossier_Benzaoui.docx"), mapping)

        self.assertNotIn("Benzaoui", masked)
        self.assertIn("Lagarde", masked)
        self.assertTrue(masked.endswith("_ANON.docx"))


if __name__ == "__main__":
    unittest.main()
