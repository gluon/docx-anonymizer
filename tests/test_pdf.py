"""Reading a PDF, which is two documents wearing one extension.

The fixture is a PDF written here, byte by byte, with a correct cross
reference table. Written rather than committed because the point is that
its text really is text: a one-page PDF produced by a word processor is
as exact as a .docx, and the piece it makes needs no proof-reading. A
committed binary would prove the same thing while hiding what is in it.

What cannot be written by hand is a scanned page, so the half of this
module that renders and recognises is covered by one test that asks for
nothing to be recognised, and by the Windows job, where the dependencies
exist.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dxanon import pdf  # noqa: E402
from dxanon.case import Case  # noqa: E402

HAS_PDF = pdf.available()


def same(text: str) -> str:
    """Normalise what extraction is allowed to change.

    A PDF stores characters, not the bytes a word processor typed:
    PDFium gives back the typographic apostrophe where the fixture
    wrote the ASCII one, and ends its lines with CRLF. Both are
    extraction, not corruption, and the piece of the case is the
    extracted text, so this is what "read exactly" can mean.
    """
    return text.replace("\u2019", "'").replace("\r\n", "\n").replace("\r", "\n")

LINES = (
    "Monsieur Jean DUPONT, demeurant 27 boulevard Chave, 13005 Marseille,",
    "a saisi le conseil de prud'hommes contre la SAS THERMOPACK INDUSTRIE,",
    "prise en la personne de Monsieur Karim BENHADDOU, son directeur.",
)


def write_pdf(path: Path, lines=LINES) -> Path:
    """A one-page PDF whose text is text, with a valid xref table."""
    body = ["BT", "/F1 12 Tf", "72 760 Td", "14 TL"]
    for line in lines:
        body.append(f"({line}) Tj")
        body.append("T*")
    body.append("ET")
    stream = "\n".join(body).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(number).encode() + b" 0 obj\n" + obj + b"\nendobj\n"

    start = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n"
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (b"trailer\n<< /Size " + str(len(objects) + 1).encode()
            + b" /Root 1 0 R >>\nstartxref\n" + str(start).encode() + b"\n%%EOF\n")
    path.write_bytes(bytes(out))
    return path


class WithoutTheLibrary(unittest.TestCase):
    def test_it_answers_rather_than_raising(self):
        self.assertIsInstance(pdf.available(), bool)
        self.assertIsInstance(pdf.diagnosis(), str)

    def test_a_reading_knows_whether_anything_was_recognised(self):
        self.assertFalse(pdf.Reading(text="x", pages=1).scanned)
        self.assertTrue(pdf.Reading(text="x", pages=2, recognised=[2]).scanned)


@unittest.skipUnless(HAS_PDF, "no PDF support in this build")
class WithTheLibrary(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = write_pdf(self.dir / "conclusions.pdf")

    def test_the_text_of_a_text_pdf_is_read_exactly(self):
        reading = pdf.read(self.path)
        self.assertEqual(reading.pages, 1)
        for line in LINES:
            self.assertIn(line.strip(), same(reading.text))

    def test_what_extraction_changes_is_the_piece(self):
        """The apostrophe comes back typographic, and that is the piece.

        Nothing restores a PDF to itself here: the piece of the case is
        the text that was read, the round trip is exact against that
        text, and the file is never rewritten. Pinned because it looks
        like a defect and is not one.
        """
        read = pdf.read(self.path).text
        self.assertIn("prud\u2019hommes", read)
        self.assertNotIn("prud'hommes", read)

    def test_a_text_pdf_is_not_a_scan(self):
        """And so its piece needs no proof-reading: it is not a guess."""
        self.assertFalse(pdf.read(self.path).scanned)
        self.assertEqual(pdf.read(self.path).recognised, [])

    def test_a_pdf_becomes_a_piece_of_the_case(self):
        case = Case(name="Dupont")
        piece = case.add_pdf(self.path)
        self.assertFalse(piece.scanned)
        self.assertFalse(piece.blocked)
        rows = {row.value for row in case.analyse().rows}
        self.assertIn("Jean DUPONT", rows)
        self.assertIn("27 boulevard Chave", rows)
        self.assertIn("Karim BENHADDOU", rows)

    def test_it_goes_out_masked_and_comes_back(self):
        case = Case(name="Dupont")
        case.add_pdf(self.path)
        case.analyse()
        outcome = case.export()[0]
        self.assertTrue(outcome.ok, outcome.refused)
        for real in ("DUPONT", "BENHADDOU", "THERMOPACK"):
            self.assertNotIn(real, outcome.text)
        back = case.restore_text(outcome.text, label=self.path.name)
        self.assertTrue(back.ok, back.refused)
        for line in LINES:
            self.assertIn(line.strip(), same(back.text))

    def test_the_same_pdf_twice_is_refused(self):
        case = Case()
        case.add_pdf(self.path)
        with self.assertRaises(ValueError):
            case.add_pdf(self.path)

    def test_an_empty_pdf_is_refused_with_words(self):
        empty = write_pdf(self.dir / "blanche.pdf", lines=())
        case = Case()
        with self.assertRaises(ValueError) as raised:
            case.add_pdf(empty)
        self.assertIn("rien n'a pu être lu", str(raised.exception))

    def test_recognition_can_be_left_out(self):
        """What a build with no engine can honestly do with a scan.

        The pages that are text are read exactly; the others are
        missing, and the window says which.
        """
        reading = pdf.read(self.path, recognise=False)
        self.assertIn(LINES[0].strip(), same(reading.text))
        self.assertEqual(reading.recognised, [])


if __name__ == "__main__":
    unittest.main()
