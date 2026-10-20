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
        self.assertIn("KARIM BENHADDOU", self.text.upper(),
                      f"read back as:\n{self.text}")

    def test_an_address_keeps_its_number_and_its_town(self):
        upper = self.text.upper()
        self.assertIn("27 BOULEVARD CHAVE", upper, f"read back as:\n{self.text}")
        self.assertIn("13005 MARSEILLE", upper, f"read back as:\n{self.text}")

    def test_what_the_engine_offers_to_change_this(self):
        """Not an assertion: the knobs this build has, printed once.

        Fails on purpose so the message travels: the machine that writes
        this code cannot install the engine, and a passing test says
        nothing anywhere.
        """
        import inspect

        from rapidocr_onnxruntime import RapidOCR

        signature = str(inspect.signature(RapidOCR.__init__))
        engine = ocr._engine()
        keys = sorted(k for k in vars(engine) if not k.startswith("__"))
        self.fail(f"RapidOCR{signature}\nattributs: {keys}\nlu:\n{self.text}")


if __name__ == "__main__":
    unittest.main()
