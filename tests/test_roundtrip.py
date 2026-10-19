"""The acceptance test: what a round trip must and must not change.

A word on what is *not* claimed here.  "Byte-for-byte identical after a
round trip" is false for any document where a replaced name was split
across runs: once ``DUP``+``ONT`` becomes ``MARTIN``+``""``, putting
``DUPONT`` back produces a single run, not the original two.  Word renders
it the same and no formatting is lost on untouched text, but the markup
differs, and a test asserting otherwise would be a test written to pass.

What is asserted instead, and is the property that actually matters:
  * a document with nothing to replace comes out byte for byte identical;
  * the full text after a round trip equals the original text;
  * every node that is not a ``<w:t>`` survives unchanged, which is what
    carries the layout: styles, justification, tracked changes, section
    properties, text boxes;
  * parts with no match are never rewritten at all.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures  # noqa: E402
from dxanon import textmap  # noqa: E402
from dxanon.engine import EmptyTable, RefusedExport, anonymize, deanonymize, scan  # noqa: E402
from dxanon.mapping import Mapping  # noqa: E402
from dxanon.package import Package  # noqa: E402


def case_mapping() -> Mapping:
    mapping = Mapping()
    mapping.add("Jean Dupont", "Marc Lemoine", kind="name")
    mapping.add("DUPONT", "LEMOINE", kind="name")
    mapping.add("Dupont", "Lemoine", kind="name")
    mapping.add("Sylvie Marchand", "Claire Riviere", kind="author")
    mapping.add("SM", "CR", kind="author")
    mapping.add("Mecanique Provencale", "Orion", kind="org")
    mapping.add("jean.dupont@example.fr", "marc.lemoine@example.fr", kind="email")
    mapping.add("Paul Girard", "Hugo Vautrin", kind="author")
    mapping.add("paul.girard@cabinet-girard.fr", "hugo.vautrin@example.invalid", kind="email")
    return mapping


def skeleton(data: bytes) -> bytes:
    """The XML with every <w:t> emptied: everything except the words."""
    root = textmap.parse(data)
    for node in root.iter(textmap.T):
        node.text = ""
    return textmap.serialize(root, data)


def text_of(path, name: str) -> str:
    with zipfile.ZipFile(path) as archive:
        return textmap.full_text(textmap.parse(archive.read(name)))


class RoundTrip(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.source = fixtures.build(self.dir / "source.docx")
        self.anon = self.dir / "anon.docx"
        self.restored = self.dir / "restored.docx"

    def test_a_table_that_matches_nothing_leaves_the_file_byte_identical(self):
        mapping = Mapping()
        mapping.add("Personne Absente", "Autre Personne")
        anonymize(self.source, self.anon, mapping)
        self.assertEqual(self.source.read_bytes(), self.anon.read_bytes())

    def test_an_empty_table_is_refused_and_writes_nothing(self):
        """Otherwise the original goes out named _ANON, in clear."""
        with self.assertRaises(EmptyTable):
            anonymize(self.source, self.anon, Mapping())
        self.assertFalse(self.anon.exists())

    def test_text_survives_the_round_trip(self):
        mapping = case_mapping()
        anonymize(self.source, self.anon, mapping)
        deanonymize(self.anon, self.restored, mapping)

        for name in ("word/document.xml", "word/header1.xml", "word/comments.xml"):
            self.assertEqual(
                text_of(self.source, name),
                text_of(self.restored, name),
                f"text changed in {name}",
            )

    def test_everything_that_is_not_a_word_survives_the_round_trip(self):
        mapping = case_mapping()
        anonymize(self.source, self.anon, mapping)
        deanonymize(self.anon, self.restored, mapping)

        with zipfile.ZipFile(self.source) as before, zipfile.ZipFile(self.restored) as after:
            self.assertEqual(before.namelist(), after.namelist())
            for name in before.namelist():
                if not name.endswith(".xml"):
                    continue
                self.assertEqual(
                    skeleton(before.read(name)),
                    skeleton(after.read(name)),
                    f"non-text markup changed in {name}",
                )

    def test_images_are_never_altered(self):
        mapping = case_mapping()
        anonymize(self.source, self.anon, mapping)
        with zipfile.ZipFile(self.source) as before, zipfile.ZipFile(self.anon) as after:
            self.assertEqual(before.read("word/media/image1.png"), after.read("word/media/image1.png"))

    def test_untouched_parts_are_not_rewritten(self):
        mapping = case_mapping()
        report = anonymize(self.source, self.anon, mapping)
        self.assertNotIn("[Content_Types].xml", report.parts_changed)
        with zipfile.ZipFile(self.source) as before, zipfile.ZipFile(self.anon) as after:
            self.assertEqual(before.read("[Content_Types].xml"), after.read("[Content_Types].xml"))


class WhereIdentityHides(unittest.TestCase):
    """Each planted value must be gone from the anonymised file."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.source = fixtures.build(self.dir / "source.docx")
        self.anon = self.dir / "anon.docx"
        anonymize(self.source, self.anon, case_mapping())
        self.package = Package.open(self.anon)

    def test_no_planted_value_survives_anywhere(self):
        for value, where in fixtures.PLANTED.items():
            with self.subTest(value=value, planted_in=where):
                self.assertEqual(scan(self.package, [value]), [])

    def test_the_tracked_change_author_is_replaced(self):
        raw = self.package.get("word/document.xml").data.decode()
        self.assertIn('w:author="Marc Lemoine"', raw)

    def test_comment_author_and_initials_are_replaced(self):
        raw = self.package.get("word/comments.xml").data.decode()
        self.assertIn('w:author="Claire Riviere"', raw)
        self.assertIn('w:initials="CR"', raw)

    def test_file_properties_are_replaced(self):
        self.assertIn("Claire Riviere", self.package.get("docProps/core.xml").data.decode())
        self.assertNotIn("Mecanique Provencale", self.package.get("docProps/app.xml").data.decode())

    def test_the_text_box_is_reached(self):
        self.assertIn("Cachet : LEMOINE", textmap.full_text(
            textmap.parse(self.package.get("word/document.xml").data)
        ))


class Refusal(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.source = fixtures.build(self.dir / "source.docx")

    def test_a_surviving_value_blocks_the_export_and_writes_nothing(self):
        source = fixtures.build_with_residue(self.dir / "residue.docx")
        destination = self.dir / "refused.docx"

        with self.assertRaises(RefusedExport) as raised:
            anonymize(source, destination, case_mapping())

        self.assertFalse(destination.exists(), "a refused export must write nothing")
        self.assertTrue(raised.exception.residues)
        self.assertIn("Sylvie Marchand", {r.value for r in raised.exception.residues})

    def test_the_check_only_protects_against_declared_values(self):
        """A stated limit, pinned by a test so it cannot be forgotten.

        The scan looks for the values in the table.  A name nobody declared
        is not searched for, so the export goes through with it still in
        place.  This is why detection and the refusal check are two
        separate lines of defence, not one.
        """
        mapping = Mapping()
        mapping.add("Sylvie Marchand", "Claire Riviere")
        destination = self.dir / "partial.docx"
        anonymize(self.source, destination, mapping)

        self.assertTrue(destination.exists())
        self.assertIn("DUPONT", text_of(destination, "word/document.xml"))

    def test_a_split_name_is_caught_by_the_scan(self):
        """The check reads reconstructed text, not raw XML.

        ``Jean DUPONT`` lives in the fixture as ``Jean DUP``+``ONT``.  A raw
        search of the markup finds nothing and would declare it clean.
        """
        package = Package.open(self.source)
        raw = package.get("word/document.xml").data.decode()
        self.assertNotIn("Jean DUPONT", raw, "fixture is no longer split; the test is void")
        self.assertTrue(scan(package, ["Jean DUPONT"]))

    def test_an_unresolved_pseudonym_blocks_the_return_trip(self):
        mapping = case_mapping()
        anon = self.dir / "anon.docx"
        anonymize(self.source, anon, mapping)

        # The model reworded a pseudonym: "Marc Lemoine" came back as
        # "Marc Lemoyne". It matches nothing, so it can never be restored,
        # and the file would go out half real and half invented.
        edited = self.dir / "edited.docx"
        _rewrite(anon, edited, "Marc Lemoine", "Marc Lemoyne")

        with self.assertRaises(RefusedExport) as raised:
            deanonymize(edited, self.dir / "restored.docx", mapping)

        self.assertFalse((self.dir / "restored.docx").exists())
        self.assertIn("Marc Lemoine", {r.value for r in raised.exception.residues})

    def test_an_extract_can_be_restored_when_the_gaps_are_expected(self):
        mapping = case_mapping()
        anon = self.dir / "anon.docx"
        anonymize(self.source, anon, mapping)
        edited = self.dir / "edited.docx"
        _rewrite(anon, edited, "Marc Lemoyne", "Marc Lemoine")

        restored = self.dir / "restored.docx"
        report = deanonymize(edited, restored, mapping, require_all=False)
        self.assertTrue(restored.exists())
        self.assertIsInstance(report.unresolved, list)


def _rewrite(source, destination, old: str, new: str) -> None:
    package = Package.open(source)
    part = package.get("word/document.xml")
    part.data = part.data.replace(old.encode(), new.encode())
    package.save(destination)


if __name__ == "__main__":
    unittest.main()
