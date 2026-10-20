"""What the engine actually reads, measured on a page it has never seen.

Written because a real run on Windows produced "THERMOPACKINDUSTRIE" and
"Directeurdesressourceshumaines" while "Sophie LENOIR" kept its space.
Every rule in this program starts from words: glued together, a company
name is one unknown token, an address is a street with no number and a
postcode with no town, and a name in the middle of a glued run is not
there at all.

The machine this was written on cannot install the engine, so the page
is drawn here, read on the job that has one, and what it read travels
back in the failure message. These tests are therefore also the
instrument: when they fail they print the text, which is the only way
that text reaches anyone.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dxanon import ocr  # noqa: E402

HAS_ENGINE = ocr.available()

LINES = (
    "SAS THERMOPACK INDUSTRIE",
    "8 chemin de la Nerthe, 13016 Marseille",
    "Madame Sophie LENOIR",
    "27 boulevard Chave, 13005 Marseille",
    "Monsieur Karim BENHADDOU, directeur",
    "des ressources humaines",
)

#: Tried in order. A runner without any of them falls back to the one
#: font OpenCV carries, which is not a scan but still has spaces in it.
FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/times.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
)


def page(path: Path) -> Path:
    """A page of printed French, as close to a scan as can be drawn."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:  # pragma: no cover - depends on the environment
        return _page_with_opencv(path)

    image = Image.new("L", (1240, 620), 248)
    draw = ImageDraw.Draw(image)
    font = None
    for candidate in FONTS:
        if Path(candidate).exists():
            font = ImageFont.truetype(candidate, 34)
            break
    y = 40
    for line in LINES:
        draw.text((60, y), line, font=font, fill=30)
        y += 60 if font else 40
    image.convert("RGB").save(path, quality=85)
    return path


def _page_with_opencv(path: Path) -> Path:  # pragma: no cover - fallback
    import cv2
    import numpy

    image = numpy.full((620, 1240), 248, dtype=numpy.uint8)
    y = 70
    for line in LINES:
        cv2.putText(image, line, (60, y), cv2.FONT_HERSHEY_DUPLEX, 1.0, 30, 2)
        y += 70
    cv2.imwrite(str(path), image)
    return path


#: What the engine really returned, on the page below, on 20 October
#: 2026. Kept verbatim: it is the measurement the splitter was written
#: against, and a sample invented afterwards would be a sample written
#: to pass.
AS_READ = """SASTHERMOPACKINDUSTRIE
8 CHEMIN DE LA NERTHE, 13016 MARSEILLE
MADAMESOPHIE LENOIR
27BOULEVARDCHAVE,13005MARSEILLE
MONSIEUR KARIMBENHADDOU, DIRECTEUR
DES RESSOURCES HUMAINES"""


class PuttingTheSpacesBack(unittest.TestCase):
    """No engine needed: the splitter against what the engine gave."""

    def setUp(self):
        self.spaced = ocr.respace(AS_READ)

    def test_a_form_of_company_is_taken_off_the_front(self):
        self.assertIn("SAS THERMOPACK INDUSTRIE", self.spaced)

    def test_a_civility_is_taken_off_the_front(self):
        self.assertIn("MADAME SOPHIE LENOIR", self.spaced)

    def test_a_number_is_split_from_the_word_after_it(self):
        self.assertIn("27 BOULEVARD CHAVE", self.spaced)
        self.assertIn("13005 MARSEILLE", self.spaced)

    def test_a_line_that_was_already_right_is_left_alone(self):
        self.assertIn("8 CHEMIN DE LA NERTHE, 13016 MARSEILLE", self.spaced)

    def test_a_name_with_no_known_word_in_it_stays_in_one_piece(self):
        """And is masked as one token, which is what matters.

        Splitting "KARIMBENHADDOU" would need a dictionary of first
        names, and a dictionary that splits names also splits words that
        merely contain one.
        """
        self.assertIn("MONSIEUR KARIMBENHADDOU", self.spaced)

    def test_nothing_is_cut_out_of_the_middle_of_a_word(self):
        self.assertEqual(ocr.respace("MARSEILLE"), "MARSEILLE")
        self.assertEqual(ocr.respace("Delacroix"), "Delacroix")
        self.assertEqual(ocr.respace("CONCLUSIONS"), "CONCLUSIONS")

    def test_what_was_typed_is_never_touched(self):
        ordinary = "Madame Sophie LENOIR, 27 boulevard Chave, 13005 Marseille."
        self.assertEqual(ocr.respace(ordinary), ordinary)

    def test_the_grid_reads_the_repaired_page(self):
        from dxanon import plaintext, workflow

        grid = workflow.build(self.spaced)
        values = {row.value for row in grid.rows}
        self.assertIn("27 BOULEVARD CHAVE", values)
        self.assertIn("THERMOPACK INDUSTRIE", values)
        self.assertIn("SOPHIE LENOIR", values)

        mapping = grid.to_mapping()
        masked = plaintext.anonymize(self.spaced, mapping)
        for real in ("LENOIR", "BENHADDOU", "THERMOPACK", "CHAVE", "NERTHE", "13005"):
            self.assertNotIn(real, masked)
        restored, missing = plaintext.deanonymize(masked, mapping)
        self.assertEqual(restored, self.spaced)
        self.assertEqual(missing, [])

    def test_a_woman_is_not_given_a_company_name(self):
        """In capitals, the civility matched nothing and she became one."""
        from dxanon import workflow

        rows = {row.value: row for row in workflow.build(self.spaced).rows}
        self.assertNotEqual(rows["SOPHIE LENOIR"].kind, "org")


@unittest.skipUnless(HAS_ENGINE, "no recognition engine in this build")
class WhatTheEngineReads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = Path(tempfile.mkdtemp())
        cls.reading = ocr.read(page(folder / "lettre.jpg"))
        cls.text = cls.reading.text

    def test_it_reads_the_page_at_all(self):
        self.assertTrue(self.text.strip(), "nothing was read from a printed page")

    def test_the_words_of_a_company_name_stay_apart(self):
        """"THERMOPACKINDUSTRIE" is one unknown token, not a company."""
        self.assertIn("THERMOPACK INDUSTRIE", self.text.upper(),
                      f"read back as:\n{self.text}")

    def test_a_name_in_the_middle_of_a_line_is_still_a_name(self):
        """Welded or not, it has to be there and it has to be masked.

        Written first as "KARIM BENHADDOU", which asked for something
        the splitter does not promise: a first name against a surname
        has no known word between them, and a dictionary of first names
        that splits those also splits words that merely contain one. One
        token, masked as one token.
        """
        from dxanon import plaintext, workflow

        self.assertIn("KARIMBENHADDOU", self.text.upper().replace(" ", ""),
                      f"read back as:\n{self.text}")
        grid = workflow.build(self.text)
        masked = plaintext.anonymize(self.text, grid.to_mapping())
        self.assertNotIn("BENHADDOU", masked.upper(), f"read back as:\n{self.text}")

    def test_an_address_keeps_its_number_and_its_town(self):
        upper = self.text.upper()
        self.assertIn("27 BOULEVARD CHAVE", upper, f"read back as:\n{self.text}")
        self.assertIn("13005 MARSEILLE", upper, f"read back as:\n{self.text}")

    def test_the_grid_finds_the_people_and_the_addresses(self):
        """End to end, on a page nobody typed: what a reader has to check.

        Four addresses, a company and a woman, from an image. The one
        thing that stays glued is a first name against a surname with no
        known word between them, and it is masked as one token, which is
        what matters.
        """
        from dxanon import workflow

        rows = {row.value.upper() for row in workflow.build(self.text).rows}
        self.assertTrue(any("LENOIR" in value for value in rows), rows)
        self.assertTrue(any("THERMOPACK" in value for value in rows), rows)
        self.assertTrue(any("BENHADDOU" in value for value in rows), rows)
        self.assertTrue(any(value.startswith("27 BOULEVARD") for value in rows), rows)


if __name__ == "__main__":
    unittest.main()
