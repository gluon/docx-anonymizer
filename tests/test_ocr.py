"""Reading a scan, and the two promises that come with it.

The engine is an optional dependency, so most of this is skipped where
it is not installed, which includes the machine this was written on:
its package index is unreachable. The Windows job is where these run,
and they are the only proof that the executable can read an image at
all.

Two of them are not about recognition. One asserts that reading a scan
opens no connection, which is the claim the whole program rests on and
the first dependency heavy enough to be worth doubting. The other
asserts that a piece read from an image cannot be exported before
somebody has looked at the text, because a misread name matches no rule
and nothing downstream can catch it.
"""

from __future__ import annotations

import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dxanon import ocr  # noqa: E402
from dxanon.case import Case  # noqa: E402
from dxanon.netguard import NetworkGuard  # noqa: E402

HAS_ENGINE = ocr.available()


def blank_png(path: Path, width: int = 240, height: int = 80) -> Path:
    """A white PNG, written by hand.

    Hand-written so this file needs no imaging library of its own: the
    point of these tests is the engine, and a test that cannot run
    without a second dependency proves less than one that can.
    """
    raw = b"".join(b"\x00" + b"\xff" * (width * 3) for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    return path


class WhatIsSaidWithoutAnEngine(unittest.TestCase):
    """The build without recognition must say so, not fail obscurely."""

    def test_an_unsupported_extension_is_named(self):
        with self.assertRaises(ValueError) as raised:
            ocr.read("piece.pdf")
        self.assertIn(".pdf", str(raised.exception))

    def test_available_answers_rather_than_raising(self):
        self.assertIsInstance(ocr.available(), bool)

    def test_a_reading_with_nothing_in_it_is_not_a_failure(self):
        empty = ocr.Reading()
        self.assertEqual(empty.text, "")
        self.assertEqual(empty.confidence, 0.0)
        self.assertEqual(empty.doubtful, [])

    def test_the_doubtful_lines_are_the_weak_ones(self):
        reading = ocr.Reading(lines=[("Monsieur DUPONT", 0.42), ("Objet", 0.99)])
        self.assertEqual(reading.doubtful, ["Monsieur DUPONT"])
        self.assertAlmostEqual(reading.confidence, 0.705, places=3)


class AScannedPieceMustBeRead(unittest.TestCase):
    """No engine needed: the rule is about the piece, not the reading."""

    def setUp(self):
        self.case = Case(name="Scan")
        self.piece = self.case.add_text("photo.png", "Monsieur DUPONT, 14 mars.")
        self.piece.scanned = True
        self.case.analyse()

    def test_it_is_not_exported_before_somebody_has_read_it(self):
        outcome = self.case.export()[0]
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.refused, ["texte issu d'une image, pas encore relu"])
        self.assertIsNone(outcome.text)

    def test_nothing_is_kept_from_an_export_that_wrote_nothing(self):
        self.case.export()
        self.assertIsNone(self.case.table)

    def test_once_read_it_goes_out_like_any_other_piece(self):
        self.piece.reviewed = True
        outcome = self.case.export()[0]
        self.assertTrue(outcome.ok, outcome.refused)
        self.assertNotIn("DUPONT", outcome.text)

    def test_a_piece_that_was_typed_needs_no_proof_reading(self):
        case = Case()
        case.add_text("note", "Monsieur DUPONT conteste.")
        case.analyse()
        self.assertTrue(case.export()[0].ok)


class WhatTheWindowShows(unittest.TestCase):
    """Two sentences that have to say opposite things."""

    def test_a_piece_says_what_it_is(self):
        from dxanon.case import Piece

        self.assertEqual(Piece("note", "x").nature, "Texte collé")
        self.assertEqual(Piece("a.docx", "x", path=Path("a.docx")).nature, "Document Word")
        scan = Piece("p.png", "x", scanned=True)
        self.assertEqual(scan.nature, "Image, à relire")
        scan.reviewed = True
        self.assertEqual(scan.nature, "Image relue")

    def test_a_missing_step_and_a_surviving_name_are_not_the_same_sentence(self):
        from dxanon.case import Outcome, why_refused

        self.assertEqual(why_refused([Outcome(label="a", written=Path("a"))]), "")
        self.assertIn("Relire le texte", why_refused([
            Outcome(label="scan", refused=["pas encore relu"], waiting=True),
        ]))
        self.assertIn("valeur réelle", why_refused([
            Outcome(label="doc", refused=["DUPONT"]),
        ]))


@unittest.skipUnless(HAS_ENGINE, "no recognition engine in this build")
class WithTheEngine(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_a_blank_page_reads_as_nothing(self):
        reading = ocr.read(blank_png(self.dir / "blanche.png"))
        self.assertEqual(reading.text.strip(), "")

    def test_reading_a_scan_opens_no_connection(self):
        """The claim the whole program rests on, against its heaviest
        dependency.

        A recognition engine that fetched a model on first use would
        send the name of nothing at all, but it would send it from a
        machine whose only promise is that nothing leaves. The guard
        counts attempts; this asserts the count is zero across a real
        recognition.
        """
        guard = NetworkGuard.install()
        try:
            ocr.read(blank_png(self.dir / "reseau.png"))
        finally:
            guard.uninstall()
        self.assertEqual(guard.attempts, [], guard.attempts)

    def test_an_unreadable_scan_is_refused_with_words(self):
        case = Case()
        with self.assertRaises(ValueError) as raised:
            case.add_scan(blank_png(self.dir / "vide.png"))
        self.assertIn("rien n'a pu être lu", str(raised.exception))
        self.assertEqual(case.pieces, [])


if __name__ == "__main__":
    unittest.main()
